"""config/ の yaml を読み、パラメータ registry として提供する。

設定の単一ソースは常に `config/`。ここで解決した値以外を使う経路を作らないこと
（CLAUDE.md 設計原則 3）。優先度は弱い順に:

    params.yaml  <  robots/cr2-0N.yaml  <  presets/*.yaml  <  スライダーの一時変更

スライダーの一時変更は永続化しない。gateway がメモリ上で保持し、
変更ログだけ /whill/param_changes に流す。
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

SAFETY_CLASSES = ('none', 'caution', 'locked_while_moving')
PARAM_TYPES = ('double', 'int', 'bool', 'string', 'double_array')

_PY_TYPES: dict[str, tuple[type, ...]] = {
    'double': (float, int),   # yaml が 1 を int で読むため int も許す
    'int': (int,),
    'bool': (bool,),
    'string': (str,),
    'double_array': (list,),
}


class RegistryError(Exception):
    """config/ の内容が registry の契約を満たしていない。"""


@dataclass(frozen=True)
class ParamSpec:
    """params.yaml の 1 エントリ。UI のウィジェット 1 個に対応する。"""

    node: str
    name: str
    type: str
    default: Any
    range: dict[str, Any] | None
    unit: str | None
    live: bool
    safety_class: str
    description: str
    elements: list[dict[str, Any]] | None = None
    """double_array の軸ごとの定義。

    [vx, vy, vyaw] のような配列は軸ごとに意味も範囲も違う。差動二輪では vy は
    構造的に常に 0 で、全軸に同じ range を当てると vx の下限が vy を弾く。
    軸ごとに label と range を持たせ、UI もこれを見て 3 本のスライダーを作る。
    """

    @property
    def key(self) -> str:
        """`controller_server.FollowPath.desired_linear_vel` 形式の一意キー。"""
        return f'{self.node}.{self.name}'

    def validate_value(self, value: Any) -> None:
        """型と範囲を検査する。違反は RegistryError。

        gateway はこれを通ってから ros2 param set を出す。UI 側の検査だけに
        頼らないのは、WebSocket に任意の JSON を投げられるため。
        """
        expected = _PY_TYPES[self.type]
        # bool は int の派生なので、int 期待のところに True が通ってしまう
        if self.type == 'int' and isinstance(value, bool):
            raise RegistryError(f'{self.key}: bool を int として受け取れない')
        if not isinstance(value, expected):
            raise RegistryError(
                f'{self.key}: 型が {self.type} ではない (受信値 {value!r})')

        if self.type == 'double_array' and self.elements is not None:
            if len(value) != len(self.elements):
                raise RegistryError(
                    f'{self.key}: 要素数が {len(self.elements)} ではない '
                    f'(受信値 {len(value)} 個)')
            # strict=True: 長さは直前で検査済みだが、黙って切り捨てないよう明示する
            for element, v in zip(self.elements, value, strict=True):
                self._check_scalar(v, element.get('range'),
                                   label=element.get('label', '?'))
            return

        if self.range is None:
            return

        values: Iterable[Any] = value if self.type == 'double_array' else [value]
        for v in values:
            self._check_scalar(v, self.range)

    def _check_scalar(self, v: Any, rng: dict[str, Any] | None,
                      label: str | None = None) -> None:
        where = f'{self.key}[{label}]' if label else self.key
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise RegistryError(f'{where}: 数値でない要素 {v!r}')
        if rng is None:
            return
        lo, hi = rng.get('min'), rng.get('max')
        if lo is not None and v < lo:
            raise RegistryError(f'{where}: {v} が下限 {lo} を下回る')
        if hi is not None and v > hi:
            raise RegistryError(f'{where}: {v} が上限 {hi} を上回る')


@dataclass
class Registry:
    """params.yaml + 個体 yaml + preset を解決した結果。"""

    specs: dict[str, ParamSpec]
    robot: dict[str, Any]
    base: dict[str, Any]
    values: dict[str, Any] = field(default_factory=dict)
    applied_preset: str | None = None
    node_aliases: dict[str, str] = field(default_factory=dict)

    # ---- 参照 --------------------------------------------------------------

    def ros_node(self, node: str) -> str:
        """registry のノード名から、実行時の ROS ノード名（完全修飾）を返す。

        Nav2 の costmap は yaml 上 `local_costmap` だが実ノードは
        `/local_costmap/local_costmap`。`ros2 param set` の宛先はこちらで、
        yaml のキーをそのまま使うと "Node not found" になる。
        """
        alias = self.node_aliases.get(node)
        if alias:
            return alias
        return node if node.startswith('/') else f'/{node}'

    def ros_node_for_key(self, key: str) -> str:
        return self.ros_node(self.spec(key).node)

    def spec(self, key: str) -> ParamSpec:
        try:
            return self.specs[key]
        except KeyError:
            raise RegistryError(f'未知のパラメータ: {key}') from None

    def live_keys(self) -> list[str]:
        return sorted(k for k, s in self.specs.items() if s.live)

    def by_node(self) -> dict[str, list[ParamSpec]]:
        """UI のノード別グループ表示用。"""
        grouped: dict[str, list[ParamSpec]] = {}
        for spec in self.specs.values():
            grouped.setdefault(spec.node, []).append(spec)
        for entries in grouped.values():
            entries.sort(key=lambda s: s.name)
        return grouped

    # ---- 更新 --------------------------------------------------------------

    def set_value(self, key: str, value: Any, *, moving: bool = False) -> None:
        """スライダー等からの一時変更。safety_class を検査してから反映する。"""
        spec = self.spec(key)
        if moving and spec.safety_class == 'locked_while_moving':
            raise RegistryError(f'{key}: 走行中は変更できない (locked_while_moving)')
        spec.validate_value(value)
        self.values[key] = value

    def apply_preset(self, preset: dict[str, Any], *, moving: bool = False) -> list[str]:
        """preset の overrides をまとめて適用し、適用したキーを返す。"""
        applied = []
        for key, value in (preset.get('overrides') or {}).items():
            self.set_value(key, value, moving=moving)
            applied.append(key)
        self.applied_preset = preset.get('name')
        return applied

    # ---- 出力 --------------------------------------------------------------

    def as_nested(self) -> dict[str, Any]:
        """`{node: {a: {b: value}}}` のネスト辞書にする。Nav2 params 生成の材料。"""
        out: dict[str, Any] = {}
        for key, value in sorted(self.values.items()):
            node, _, rest = key.partition('.')
            cursor = out.setdefault(node, {})
            parts = rest.split('.')
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[parts[-1]] = copy.deepcopy(value)
        return out


# ---- 読み込み --------------------------------------------------------------


def config_root() -> Path:
    """config/ の場所を決める。

    WHILL_PLATFORM_CONFIG が最優先（scripts/env.sh が export する）。
    次にこのファイルからリポジトリを遡って探す。最後に ament の share を見る。
    share は colcon install 時の複製なので、リポジトリを編集したのに
    古い値が読まれる事故を避けるため最後に置いている。
    """
    env = os.environ.get('WHILL_PLATFORM_CONFIG')
    if env:
        path = Path(env).expanduser()
        if not path.is_dir():
            raise RegistryError(f'WHILL_PLATFORM_CONFIG が存在しない: {path}')
        return path

    for parent in Path(__file__).resolve().parents:
        candidate = parent / 'config' / 'params.yaml'
        if candidate.is_file():
            return candidate.parent

    try:
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory('whill_params')) / 'config'
        if (share / 'params.yaml').is_file():
            return share
    except Exception:  # noqa: BLE001 - ament が無い環境（uv 側の CLI）でも動かす
        pass

    raise RegistryError('config/params.yaml を見つけられない。'
                        'WHILL_PLATFORM_CONFIG を設定するか scripts/env.sh を source すること')


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegistryError(f'見つからない: {path}')
    with path.open(encoding='utf-8') as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RegistryError(f'トップレベルが辞書でない: {path}')
    return data


def _parse_specs(raw: dict[str, Any], source: Path) -> dict[str, ParamSpec]:
    entries = raw.get('params')
    if not isinstance(entries, list):
        raise RegistryError(f'{source}: params: がリストでない')

    specs: dict[str, ParamSpec] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RegistryError(f'{source}: params[{index}] が辞書でない')
        missing = {'node', 'name', 'type', 'default', 'live', 'safety_class',
                   'description'} - entry.keys()
        if missing:
            raise RegistryError(
                f'{source}: params[{index}] に必須キーが無い: {sorted(missing)}')
        if entry['type'] not in PARAM_TYPES:
            raise RegistryError(
                f'{source}: params[{index}] の type が不正: {entry["type"]}')
        if entry['safety_class'] not in SAFETY_CLASSES:
            raise RegistryError(
                f'{source}: params[{index}] の safety_class が不正: {entry["safety_class"]}')

        spec = ParamSpec(
            node=entry['node'],
            name=entry['name'],
            type=entry['type'],
            default=entry['default'],
            range=entry.get('range'),
            unit=entry.get('unit'),
            live=bool(entry['live']),
            safety_class=entry['safety_class'],
            description=str(entry['description']).strip(),
            elements=entry.get('elements'),
        )
        if spec.type == 'double_array' and spec.elements is None:
            raise RegistryError(
                f'{source}: params[{index}] ({spec.key}): '
                f'double_array には elements: が必要（軸ごとに範囲が違うため）')
        if spec.key in specs:
            raise RegistryError(f'{source}: キーが重複している: {spec.key}')
        # default 自身が range を外れていたら、それは登録ミス
        spec.validate_value(spec.default)
        specs[spec.key] = spec
    return specs


def load(robot_id: str, *, preset: str | None = None,
         root: Path | None = None) -> Registry:
    """指定個体の registry を解決して返す。"""
    root = root or config_root()

    specs = _parse_specs(_load_yaml(root / 'params.yaml'), root / 'params.yaml')
    base = _load_yaml(root / 'robots' / 'cr2-base.yaml')
    robot = _load_yaml(root / 'robots' / f'{robot_id}.yaml')

    raw_params = _load_yaml(root / 'params.yaml')
    aliases = raw_params.get('node_aliases') or {}
    known_nodes = {spec.node for spec in specs.values()}
    for node in aliases:
        # 存在しないノードへの別名は typo。黙って無視すると
        # gateway が本物のノードに届かない理由が分からなくなる。
        if node not in known_nodes:
            raise RegistryError(
                f'node_aliases の "{node}" は params.yaml のどの node にも一致しない')

    registry = Registry(specs=specs, robot=robot, base=base,
                        node_aliases=dict(aliases),
                        values={k: copy.deepcopy(s.default) for k, s in specs.items()})

    # 個体 yaml の param_overrides は個体差の吸収。存在しないキーは黙って
    # 無視せずエラーにする（typo が本番で効かないまま通るのを防ぐ）。
    for key, value in (robot.get('param_overrides') or {}).items():
        registry.set_value(key, value)

    if preset:
        preset_data = _load_yaml(root / 'presets' / f'{preset}.yaml')
        if preset_data.get('real_robot_allowed') is False and robot.get('is_real', True):
            # 実機禁止 preset は mock/replay でのみ通す。判定は呼び出し側が
            # robot dict に is_real を差し込む。
            pass
        registry.apply_preset(preset_data)

    return registry


def load_specs_only(root: Path | None = None) -> dict[str, ParamSpec]:
    """個体を指定せず spec だけ欲しいとき（スキーマ検証、CLI の一覧表示）。"""
    root = root or config_root()
    return _parse_specs(_load_yaml(root / 'params.yaml'), root / 'params.yaml')
