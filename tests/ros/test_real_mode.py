"""mode=real の配線（#77、K5）。

**実機では起動確認をしていない。** 実機が手元にないので、ここで確かめられるのは
「何を起動し、何を起動しないか」まで。起動の確認は `docs/phase7-checklist.md` の段 0。

見たいのは、**二重に起動しないこと**が中心:

  - static TF … 既存スタックの `sensors_launch` が出す。本リポが出すと 2 つになる
  - twist_mux … 既存の `safety_launch` が起動する（優先度つき）
  - EKF・localizer … 既存の `m6r_bringup_launch` が起動する
  - Nav2 … **本リポが起動する**（registry から生成した params を使うため）

launch の記述を組み立てるところまでは、既存スタックが入っていれば実際に走らせて
確かめられる（プロセスは起動しない）。CI には既存スタックが無いので skip される。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
LAUNCH_FILE = ROOT / 'ros' / 'src' / 'whill_bringup' / 'launch' / 'bringup_launch.py'
LAUNCH = LAUNCH_FILE.read_text('utf-8')
sys.path.insert(0, str(ROOT / 'ros' / 'src' / 'whill_bringup'))

EXISTING_STACK = Path.home() / 'whill_lab0_ros2'


def _robot(robot_id: str = 'cr2-01') -> dict:
    return yaml.safe_load((ROOT / 'config' / 'robots' / f'{robot_id}.yaml').read_text('utf-8'))


# ---- 配線の形（既存スタックが無くても確かめられる）--------------------------


def test_real_is_wired():
    assert 'mode=real はまだ配線していない' not in LAUNCH
    assert '_real_actions(robot, use_camera)' in LAUNCH


def test_real_includes_the_existing_stack():
    """センサ・実ドライバ・EKF・localizer・failsafe・twist_mux はあちらが起動する。"""
    assert "'m6r_bringup_launch.py'" in LAUNCH
    assert "_require_existing_stack('whill_safety')" in LAUNCH


def test_real_borrows_only_ground_removal_from_nav_launch():
    """`nav_launch.py` は params を受け取れないので include しない（設計原則 3）。"""
    assert "'ground_removal_launch.py'" in LAUNCH
    # include するときはパスの部品として引用符で囲む。説明の文中に出てくるのは別。
    assert "'nav_launch.py'" not in LAUNCH


@pytest.mark.parametrize('what, modes', [
    ('_static_tf_nodes(robot, use_sim_time)', "if mode in ('mock', 'sim'):"),
    ('twist_mux', "if mode in ('mock', 'sim'):"),
    ('ekf_odom_launch.py', "if mode in ('mock', 'sim'):"),
])
def test_things_the_existing_stack_provides_are_not_started_twice(what, modes):
    """real で本リポも起動すると、TF が二重になり twist_mux が 2 つになる。"""
    index = LAUNCH.index(what)
    preceding = LAUNCH[:index]
    guard = preceding.rindex("if mode in (")
    assert LAUNCH[guard:index].startswith(modes), f'{what} が real でも起動する配線になっている'


def test_scan_chain_matches_the_real_robot():
    """実機の /scan は地面除去のあとの点群から作る（生の点群からではない）。"""
    real = LAUNCH[LAUNCH.index('def _real_actions'):LAUNCH.index('def _static_tf_nodes')]
    assert "('cloud_in', '/velodyne_points_no_ground')" in real
    assert "'pointcloud_to_laserscan.yaml'" in real


def test_map_comes_from_the_robot_yaml():
    assert "_existing_repo_path(_map_entry(robot), 'occupancy')" in LAUNCH


# ---- 設定（地図と site）-----------------------------------------------------


@pytest.mark.parametrize('robot_id', ['cr2-01', 'cr2-02', 'cr2-03'])
def test_every_robot_declares_a_site_and_a_map(robot_id):
    """localizer に渡す site 名を**パスから推測しない**。"""
    maps = _robot(robot_id)['maps']
    entry = maps[maps['default']]
    assert entry['site']
    assert entry['occupancy'].endswith('.yaml')
    assert entry['waypoints'].endswith('.yaml')


@pytest.mark.skipif(not EXISTING_STACK.is_dir(), reason='既存スタックが無い')
@pytest.mark.parametrize('key', ['occupancy', 'waypoints'])
def test_declared_paths_exist_in_the_existing_repo(key):
    """以前 `docs/maps/campus/v2/occupancy_v2.yaml` と 1 階層ずれていた（#77 で発見）。"""
    maps = _robot()['maps']
    entry = maps[maps['default']]
    path = (Path(entry['source_repo']).expanduser() / entry[key])
    assert path.is_file(), path


@pytest.mark.skipif(not EXISTING_STACK.is_dir(), reason='既存スタックが無い')
def test_the_map_is_the_variant_the_existing_runbook_requires():
    """既存リポの runbook は `map_variant:=v2` が必須と書いている
    （無指定の occupancy.yaml には焼き込みの残りがある）。"""
    maps = _robot()['maps']
    assert maps[maps['default']]['occupancy'].endswith('occupancy_v2.yaml')


# ---- 実際に launch 記述を組み立てる（プロセスは起動しない）------------------


def _build(mode: str, robot_id: str = 'cr2-01'):
    """`_setup` を呼んで actions を作る。**ノードは起動しない。**"""
    from launch import LaunchContext
    from launch.actions import DeclareLaunchArgument

    sys.path.insert(0, str(ROOT / 'ros' / 'src' / 'whill_bringup' / 'launch'))
    import bringup_launch

    context = LaunchContext()
    defaults = {'robot_id': robot_id, 'mode': mode, 'preset': '', 'use_camera': 'false',
                'bag': '', 'autostart': 'true', 'gateway': 'false'}
    for name, value in defaults.items():
        DeclareLaunchArgument(name, default_value=value).visit(context)
    return bringup_launch._setup(context), context


def _included(actions, context) -> set[str]:
    from launch.actions import IncludeLaunchDescription

    names = set()
    for action in actions:
        if not isinstance(action, IncludeLaunchDescription):
            continue
        # `location` は substitution のリスト（str に見える property は repr）。
        parts = action.launch_description_source._LaunchDescriptionSource__location
        if isinstance(parts, str):
            location = parts
        else:
            location = ''.join(part.perform(context) for part in parts)
        names.add(Path(location).name)
    return names


def _executables(actions) -> set[str]:
    from launch_ros.actions import Node

    return {getattr(a, '_Node__node_executable', None) for a in actions if isinstance(a, Node)}


@pytest.mark.skipif(not EXISTING_STACK.is_dir(), reason='既存スタックが無い')
def test_real_starts_the_existing_stack_and_nav2_and_nothing_else():
    """組み立てた中身を見る。**起動はしない**（実機が無いと動かない）。"""
    pytest.importorskip('launch')
    actions, context = _build('real')

    includes = _included(actions, context)
    assert 'm6r_bringup_launch.py' in includes, 'センサ・ドライバ・EKF・localizer'
    assert 'ground_removal_launch.py' in includes, '地面除去'
    assert 'navigation_launch.py' in includes, 'Nav2 は本リポが起動する'
    assert 'nav_launch.py' not in includes, '既存の Nav2 一式を二重に起動しない'
    assert 'ekf_odom_launch.py' not in includes, 'EKF は m6r_bringup が起動する'

    executables = _executables(actions)
    assert 'pointcloud_to_laserscan_node' in executables
    assert 'map_server' in executables
    assert 'dispatch_node' in executables
    # 既存スタックが出すものを二重に起動しない
    assert 'static_transform_publisher' not in executables
    assert 'twist_mux' not in executables


@pytest.mark.skipif(not EXISTING_STACK.is_dir(), reason='既存スタックが無い')
def test_mock_still_starts_what_the_existing_stack_would_have():
    """real で外したものが、mock からも消えていないこと。"""
    actions, context = _build('mock')
    executables = _executables(actions)
    assert 'static_transform_publisher' in executables
    assert 'twist_mux' in executables
    assert 'ekf_odom_launch.py' in _included(actions, context)


@pytest.mark.skipif(not EXISTING_STACK.is_dir(), reason='既存スタックが無い')
def test_real_map_server_gets_the_robots_map():
    from launch_ros.actions import Node

    actions, context = _build('real')
    maps = _robot()['maps']
    expected = str((Path(maps[maps['default']]['source_repo']).expanduser()
                    / maps[maps['default']]['occupancy']))

    def resolve(value):
        """パラメータの値は substitution のタプルで、中身は YAML（末尾に `...`）。"""
        if isinstance(value, (list, tuple)):
            value = ''.join(part.perform(context) for part in value)
        if isinstance(value, str):
            return yaml.safe_load(value)
        return value

    for action in actions:
        if isinstance(action, Node) and getattr(action, '_Node__node_executable', '') == 'map_server':
            values = [resolve(v) for block in action._Node__parameters if isinstance(block, dict)
                      for key, v in block.items() if resolve(key) == 'yaml_filename']
            assert values == [expected], values
            break
    else:
        pytest.fail('map_server が組み立てに入っていない')


@pytest.mark.skipif(not EXISTING_STACK.is_dir(), reason='既存スタックが無い')
def test_missing_map_is_reported_with_the_path():
    """黙って空の地図で上がると、Nav2 が経路を引けない理由が分からない。"""
    sys.path.insert(0, str(ROOT / 'ros' / 'src' / 'whill_bringup' / 'launch'))
    import bringup_launch

    entry = dict(_robot()['maps']['campus_v2'])
    entry['occupancy'] = 'docs/maps/campus/no-such-map.yaml'
    with pytest.raises(RuntimeError, match='no-such-map'):
        bringup_launch._existing_repo_path(entry, 'occupancy')


def test_docs_say_it_is_unverified_on_hardware():
    """**「実機モードで動いたつもり」を作らない。** 未確認であることを書いておく。"""
    assert '実機では起動確認をしていない' in LAUNCH
    checklist = (ROOT / 'docs' / 'phase7-checklist.md').read_text('utf-8')
    assert re.search(r'mode real|mode=real|--mode real', checklist)
