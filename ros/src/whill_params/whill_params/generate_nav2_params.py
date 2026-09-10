"""registry から Nav2 の params yaml を生成する。

既存 `whill_lab0_ros2/src/whill_navigation/config/nav2_params.yaml` を
テンプレートとして読み、registry が管理しているキーだけを差し替える。全文を
ゼロから組み立てないのは、Nav2 の params には registry に載せる価値のない
定型（plugin 名の羅列、BT の xml パス等）が大量にあり、それを二重管理すると
必ず食い違うため。registry は「人が触る値」だけを持つ。

Phase 1 の受け入れ条件:
    テンプレートに対して --check を走らせ、既定値のみで差分ゼロになること。
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from whill_params import registry as reg

DEFAULT_TEMPLATE = Path('~/whill_lab0_ros2/src/whill_navigation/config/nav2_params.yaml')


def _ros_parameters(root: dict[str, Any], node: str) -> dict[str, Any] | None:
    """ノード名から `ros__parameters` の辞書を引く。

    Nav2 の costmap は名前空間とノード名が同じため二重に入れ子になる:

        local_costmap:
          local_costmap:
            ros__parameters: ...

    一方 controller_server などは一段:

        controller_server:
          ros__parameters: ...

    両方を扱う。ここを一段しか見ないと costmap 系のキーが黙って書かれず、
    「差分なし」と表示されるのに実際は既定値が反映されていない、という
    最悪の嘘をつく（実際に Phase 1 着手時点でそうなっていた）。
    """
    node_block = root.get(node)
    if not isinstance(node_block, dict):
        return None

    direct = node_block.get('ros__parameters')
    if isinstance(direct, dict):
        return direct

    nested = node_block.get(node)
    if isinstance(nested, dict) and isinstance(nested.get('ros__parameters'), dict):
        return nested['ros__parameters']

    return None


def iter_ros_parameters(root: dict[str, Any]):
    """テンプレート内の全 `ros__parameters` 辞書を返す（入れ子も拾う）。

    bringup が use_sim_time を流し込むのにも使う。costmap の二重入れ子を
    見落とすと replay モードで costmap だけ実時刻を見る。
    """
    for node_block in root.values():
        if not isinstance(node_block, dict):
            continue
        direct = node_block.get('ros__parameters')
        if isinstance(direct, dict):
            yield direct
        for child in node_block.values():
            if isinstance(child, dict) and isinstance(child.get('ros__parameters'), dict):
                yield child['ros__parameters']


def _set_nested(root: dict[str, Any], node: str, dotted: str, value: Any) -> bool:
    """Nav2 params の `<node>: ros__parameters: <a>: <b>` へ値を書く。

    書けたら True。テンプレートに該当パスが無ければ False（登録ミスの検出用）。
    """
    cursor = _ros_parameters(root, node)
    if cursor is None:
        return False

    parts = dotted.split('.')
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            return False
        cursor = nxt
    if parts[-1] not in cursor:
        return False
    cursor[parts[-1]] = copy.deepcopy(value)
    return True


VIRTUAL_OBSTACLES_PLUGIN = 'whill_virtual_obstacles'
"""仮想障害物層の plugin 名。costmap の `plugins` に足す名前。"""

# registry が持たない構造上のキー。値ではなく「層を足すかどうか」なので、
# テンプレートに書き込むのではなく生成側で組み立てる。
_STRUCTURAL_KEYS = {'virtual_obstacles_enabled'}


def _insert_virtual_obstacles(params: dict[str, Any], node: str) -> None:
    """costmap の plugins に仮想障害物層を足し、そのパラメータ塊を作る。

    plugins の並びは構造であって「人が触る値」ではないので registry には
    載せない（ADR-0001）。registry が持つのは on/off だけで、どこに挿すかは
    ここが決める。

    **`inflation_layer` より前に挿す。** 後ろだと膨張がかからず、車体が
    入れない隙間を通る経路が出る。
    """
    block = _ros_parameters(params, node)
    if block is None:
        return

    plugins = block.get('plugins')
    if not isinstance(plugins, list):
        return
    if VIRTUAL_OBSTACLES_PLUGIN in plugins:
        return

    if 'inflation_layer' in plugins:
        plugins.insert(plugins.index('inflation_layer'), VIRTUAL_OBSTACLES_PLUGIN)
    else:
        plugins.append(VIRTUAL_OBSTACLES_PLUGIN)

    block[VIRTUAL_OBSTACLES_PLUGIN] = {
        'plugin': 'whill_costmap_plugins::VirtualObstaclesLayer',
        'enabled': True,
        'topic': '/whill/virtual_obstacles',
        'max_radius': 5.0,
    }


def render(robot_id: str, template_path: Path, preset: str | None = None,
           overrides: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """生成後の yaml 文字列と、テンプレートに反映できなかったキーを返す。

    `overrides` は registry の値を一時的に差し替える。preset を作るほどでは
    ない一回限りの確認（「この層を切ったら差分ゼロに戻るか」等）に使う。
    """
    with template_path.open(encoding='utf-8') as handle:
        template = yaml.safe_load(handle)

    registry = reg.load(robot_id, preset=preset)
    for key, value in (overrides or {}).items():
        registry.set_value(key, value)
    unmapped: list[str] = []
    for key, value in registry.values.items():
        node, _, dotted = key.partition('.')
        # gateway 等 Nav2 の管轄外ノードはテンプレートに存在しなくて当然
        if node not in template:
            continue
        if dotted in _STRUCTURAL_KEYS:
            # 値ではなく構造。plugins の組み立てで扱う。
            if dotted == 'virtual_obstacles_enabled' and value:
                _insert_virtual_obstacles(template, node)
            continue
        if not _set_nested(template, node, dotted, value):
            unmapped.append(key)

    text = yaml.safe_dump(template, allow_unicode=True, sort_keys=False,
                          default_flow_style=False, width=100)
    return text, sorted(unmapped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='generate_nav2_params',
        description='config/ の registry から Nav2 params を生成する')
    parser.add_argument('--robot', default='cr2-01', help='個体 ID (既定 cr2-01)')
    parser.add_argument('--preset', default=None, help='適用する preset 名')
    parser.add_argument('--template', type=Path, default=DEFAULT_TEMPLATE,
                        help='ベースにする既存 nav2_params.yaml')
    parser.add_argument('-o', '--output', type=Path, default=None,
                        help='出力先。省略時は標準出力')
    parser.add_argument('--check', action='store_true',
                        help='書き出さず、テンプレートとの意味的な差分だけ報告する')
    parser.add_argument('--set', action='append', default=[], metavar='KEY=VALUE',
                        help='registry の値を一時的に差し替える（複数可）')
    args = parser.parse_args(argv)

    overrides: dict[str, Any] = {}
    for entry in args.set:
        if '=' not in entry:
            print(f'--set は KEY=VALUE の形で指定すること: {entry}', file=sys.stderr)
            return 2
        key, _, raw = entry.partition('=')
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[key] = raw

    template_path = args.template.expanduser()
    if not template_path.is_file():
        print(f'テンプレートが無い: {template_path}', file=sys.stderr)
        return 2

    try:
        text, unmapped = render(args.robot, template_path, args.preset, overrides)
    except reg.RegistryError as exc:
        print(f'registry エラー: {exc}', file=sys.stderr)
        return 2

    for key in unmapped:
        print(f'エラー: テンプレートに該当パスが無い: {key}', file=sys.stderr)

    if args.check:
        # 反映できなかったキーがあるまま「差分なし」と言わない。書かれていない
        # キーは当然テンプレートと一致するので、値比較だけでは素通りしてしまう。
        # registry が管理しているつもりの値が実は効いていない、という嘘を
        # ここで止める。
        if unmapped:
            print(f'{len(unmapped)} 件が反映されていない。'
                  f'registry のキー名かテンプレートの構造を直すこと', file=sys.stderr)
            return 1

        with template_path.open(encoding='utf-8') as handle:
            original = yaml.safe_load(handle)
        generated = yaml.safe_load(text)
        if original == generated:
            print('差分なし')
            return 0
        # コメントや並び順ではなく値の差だけを見たいので、正規化してから比較する
        diff = difflib.unified_diff(
            yaml.safe_dump(original, allow_unicode=True, sort_keys=True).splitlines(),
            yaml.safe_dump(generated, allow_unicode=True, sort_keys=True).splitlines(),
            fromfile='template', tofile='generated', lineterm='')
        print('\n'.join(diff))
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
        print(f'書き出した: {args.output}')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
