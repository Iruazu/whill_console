"""CLI 側から config/ を読むための薄いラッパ。

ROS 側の whill_params.registry と同じ yaml を読むが、CLI は colcon の外で
動くため rclpy に依存できない。registry の完全な再実装はせず、CLI が必要と
する範囲（個体一覧、モード一覧、宣言トピック、live 一覧）だけを持つ。

registry 本体のロジックを二重化しないよう、ROS ws が source されていて
whill_params が import できる場合はそちらを優先して使う。
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """config/ が見つからない、または内容が壊れている。"""


@lru_cache(maxsize=1)
def config_root() -> Path:
    """config/ の場所。WHILL_PLATFORM_CONFIG が最優先。"""
    env = os.environ.get('WHILL_PLATFORM_CONFIG')
    if env:
        path = Path(env).expanduser()
        if not path.is_dir():
            raise ConfigError(f'WHILL_PLATFORM_CONFIG が存在しない: {path}')
        return path

    for parent in Path(__file__).resolve().parents:
        candidate = parent / 'config' / 'params.yaml'
        if candidate.is_file():
            return candidate.parent
    raise ConfigError(
        'config/params.yaml を見つけられない。scripts/env.sh を source するか '
        'WHILL_PLATFORM_CONFIG を設定すること')


def repo_root() -> Path:
    return config_root().parent


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f'見つからない: {path}')
    with path.open(encoding='utf-8') as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigError(f'トップレベルが辞書でない: {path}')
    return data


def base_config() -> dict[str, Any]:
    return load_yaml(config_root() / 'robots' / 'cr2-base.yaml')


def robot_config(robot_id: str) -> dict[str, Any]:
    path = config_root() / 'robots' / f'{robot_id}.yaml'
    if not path.is_file():
        raise ConfigError(f'未知の個体: {robot_id} (候補: {", ".join(known_robots())})')
    return load_yaml(path)


def known_robots() -> list[str]:
    root = config_root() / 'robots'
    return sorted(p.stem for p in root.glob('cr2-*.yaml') if p.stem != 'cr2-base')


def known_presets() -> list[str]:
    return sorted(p.stem for p in (config_root() / 'presets').glob('*.yaml'))


def known_modes() -> list[str]:
    return sorted((base_config().get('modes') or {}).keys())


def declared_topics(robot_id: str, mode: str, *, include_camera: bool = False) -> list[str]:
    """そのモードで publish されるはずのトピック一覧。

    Phase 0 の受け入れ判定（`whill doctor`）はこの一覧を正として
    `ros2 topic list` と突き合わせる。
    """
    base = base_config()
    modes = base.get('modes') or {}
    if mode not in modes:
        raise ConfigError(f'未知のモード: {mode} (候補: {", ".join(sorted(modes))})')

    drivers = list(modes[mode].get('drivers') or [])
    if include_camera and 'realsense' not in drivers:
        drivers.append('realsense')

    # ドライバ以外が出すもの（sim の Gazebo プラグインなど）
    topics: list[str] = list(modes[mode].get('publishes') or [])
    for driver in drivers:
        declaration = (base.get('drivers') or {}).get(driver) or {}
        for entry in declaration.get('publishes') or []:
            topics.append(entry['topic'])
        # telemetry が別トピックを参照している場合もそれは「出るはず」の対象
        for entry in declaration.get('telemetry') or []:
            topic = entry.get('topic')
            if topic and topic not in topics:
                topics.append(topic)
    return sorted(set(topics))


def declared_telemetry(robot_id: str, mode: str) -> dict[str, str]:
    """そのモードで出るはずのテレメトリ項目 → ドライバ名。

    `whill measure telemetry` が実物と突き合わせるのに使う。宣言が正
    （`cr2-base.yaml`）で、食い違ったら**宣言か実装のどちらかが古い**。
    """
    base = base_config()
    modes = base.get('modes') or {}
    if mode not in modes:
        raise ConfigError(f'未知のモード: {mode} (候補: {", ".join(sorted(modes))})')

    drivers = list(modes[mode].get('drivers') or [])
    declared: dict[str, str] = {}
    for driver in drivers:
        declaration = (base.get('drivers') or {}).get(driver) or {}
        for entry in declaration.get('telemetry') or []:
            declared[entry['name']] = driver
    # 派生テレメトリは単一のドライバに属さない。モードに関係なく出る。
    for entry in base.get('derived_telemetry') or []:
        declared[entry['name']] = 'derived'
    return declared


def derived_without_inputs(mode: str) -> set[str]:
    """そのモードでは入力が出ないので、値が出なくて当然の派生テレメトリ。

    `derived_telemetry.inputs` のトピックが、そのモードのドライバ宣言に
    無ければ計算しようがない（mock には scan-to-map localizer が居ないので
    `/pcl_pose` が出ず、`yaw_rate_vs_ndt` は出ない）。**故障と区別する。**
    """
    base = base_config()
    available = set(declared_topics_for_mode(mode))
    out = set()
    for entry in base.get('derived_telemetry') or []:
        inputs = set(entry.get('inputs') or [])
        if inputs - available:
            out.add(entry['name'])
    return out


def declared_topics_for_mode(mode: str) -> list[str]:
    """そのモードで出るはずのトピック（`declared_topics` の robot 非依存版）。"""
    return declared_topics('cr2-01', mode)


def command_topic() -> str:
    """実ドライバが受ける速度指令のトピック。`cr2-base.yaml` の subscribes が正。"""
    base = base_config()
    subscribes = ((base.get('drivers') or {}).get('whill_serial') or {}).get('subscribes') or []
    for entry in subscribes:
        if entry.get('type', '').endswith('Twist'):
            return entry['topic']
    raise ConfigError('cr2-base.yaml の whill_serial.subscribes に Twist の宣言が無い')


def registry_module():
    """whill_params が import できるならそれを返す。できなければ None。

    ROS ws を source していない状態でも CLI の一覧表示は動いてほしいので、
    import 失敗を致命的にしない。
    """
    try:
        import whill_params.registry as module
        return module
    except ImportError:
        return None


def require_registry():
    module = registry_module()
    if module is None:
        print('whill_params を import できない。ros/install/setup.bash を source すること',
              file=sys.stderr)
        raise SystemExit(2)
    return module
