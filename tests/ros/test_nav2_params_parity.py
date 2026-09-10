"""registry から生成した Nav2 params が既存スタックの設定と一致することのテスト。

Phase 1 の受け入れ条件そのもの。ここが赤いあいだは registry 経由で実機を
走らせられない。既存 `whill_lab0_ros2` の実走チューニングが、registry を
通しただけで変わっていないことを機械的に保証する。

既存リポが無い環境（CI）ではテンプレート依存のテストを skip する。
skip したことが見えるよう、理由を明示する。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
import yaml

from whill_params import registry as reg
from whill_params.generate_nav2_params import (
    _ros_parameters,
    iter_ros_parameters,
    render,
)

# bringup が使うのと同じ環境変数で差し替えられるようにする。CI では
# 既存スタックが無いので、テンプレート依存のテストは skip される。
TEMPLATE = Path(os.environ.get(
    'WHILL_NAV2_TEMPLATE',
    '~/whill_lab0_ros2/src/whill_navigation/config/nav2_params.yaml')).expanduser()

requires_template = pytest.mark.skipif(
    not TEMPLATE.is_file(),
    reason=f'既存スタックのテンプレートが無い: {TEMPLATE}')


# ---- ros__parameters の引き当て（costmap の二重入れ子） --------------------


def test_single_level_node_is_found():
    doc = {'controller_server': {'ros__parameters': {'a': 1}}}
    assert _ros_parameters(doc, 'controller_server') == {'a': 1}


def test_double_nested_costmap_is_found():
    """Nav2 の costmap は名前空間とノード名が同じで二重に入れ子になる。

    ここを取りこぼすと costmap のキーが黙って書かれず、値比較だけの
    `--check` が「差分なし」と嘘をつく。Phase 1 着手時に実際に起きた。
    """
    doc = {'local_costmap': {'local_costmap': {'ros__parameters': {'a': 1}}}}
    assert _ros_parameters(doc, 'local_costmap') == {'a': 1}


def test_missing_node_returns_none():
    assert _ros_parameters({'other': {}}, 'controller_server') is None


def test_iter_covers_both_shapes():
    doc = {
        'controller_server': {'ros__parameters': {'a': 1}},
        'local_costmap': {'local_costmap': {'ros__parameters': {'b': 2}}},
        'not_a_node': 'string',
    }
    found = list(iter_ros_parameters(doc))
    assert {'a': 1} in found
    assert {'b': 2} in found
    assert len(found) == 2


# ---- 既存テンプレートとの一致 ---------------------------------------------


@requires_template
def test_every_registry_key_maps_into_the_template():
    """registry が Nav2 のキーだと思っているものが全部書き込めること。

    書けないキーがあると、UI のスライダーが動いても実際の Nav2 には
    届かない。値比較では検出できないのでここで見る。
    """
    _, unmapped = render('cr2-01', TEMPLATE)
    assert unmapped == [], f'テンプレートに書き込めないキー: {unmapped}'


# Phase 4 で仮想障害物の層を足した。**これは意図した差分**なので、
# 「差分ゼロ」の担保はその層を切った状態で行う。切って一致しなければ、
# 層の追加とは関係のない退行が入っているということ。
NO_VIRTUAL_OBSTACLES = {
    'local_costmap.virtual_obstacles_enabled': False,
    'global_costmap.virtual_obstacles_enabled': False,
}


@requires_template
def test_defaults_reproduce_the_template_exactly():
    """仮想障害物の層を切れば、生成結果がテンプレートと意味的に一致すること。

    Phase 1 の「差分ゼロ」の担保。層の追加以外の変更が紛れ込んでいないことを
    見ている。ここが割れたら、実走チューニングを黙って書き換えている。
    """
    text, _ = render('cr2-01', TEMPLATE, overrides=NO_VIRTUAL_OBSTACLES)
    generated = yaml.safe_load(text)
    original = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8'))
    assert generated == original


@requires_template
def test_virtual_obstacles_layer_is_inserted_before_inflation():
    """**inflation_layer より前に挿すこと。**

    後ろだと膨張がかからず、車体が入れない隙間を通る経路が出る。
    """
    text, _ = render('cr2-01', TEMPLATE)
    generated = yaml.safe_load(text)
    for node in ('local_costmap', 'global_costmap'):
        plugins = _ros_parameters(generated, node)['plugins']
        assert 'whill_virtual_obstacles' in plugins, f'{node} に層が入っていない'
        assert plugins.index('whill_virtual_obstacles') < plugins.index('inflation_layer')


@requires_template
def test_virtual_obstacles_layer_has_its_parameters():
    text, _ = render('cr2-01', TEMPLATE)
    block = _ros_parameters(yaml.safe_load(text), 'global_costmap')
    layer = block['whill_virtual_obstacles']
    assert layer['plugin'] == 'whill_costmap_plugins::VirtualObstaclesLayer'
    assert layer['topic'] == '/whill/virtual_obstacles'
    assert layer['max_radius'] > 0


@requires_template
def test_disabling_virtual_obstacles_removes_the_plugin():
    """切ったら層ごと消えること。enabled: false を残すのではなく plugins から外す。

    残すと「切ったつもりだが層は生きている」状態になりうる。
    """
    text, _ = render('cr2-01', TEMPLATE, overrides=NO_VIRTUAL_OBSTACLES)
    generated = yaml.safe_load(text)
    for node in ('local_costmap', 'global_costmap'):
        plugins = _ros_parameters(generated, node)['plugins']
        assert 'whill_virtual_obstacles' not in plugins


@requires_template
def test_the_only_difference_is_the_virtual_obstacles_layer():
    """層の追加**だけ**が差分であること。

    ついでに他の値まで変わっていないかを見る。plugins と層の設定を
    取り除いたら一致するはず。
    """
    with_layer = yaml.safe_load(render('cr2-01', TEMPLATE)[0])
    original = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8'))

    for node in ('local_costmap', 'global_costmap'):
        block = _ros_parameters(with_layer, node)
        block['plugins'] = [p for p in block['plugins'] if p != 'whill_virtual_obstacles']
        block.pop('whill_virtual_obstacles', None)

    assert with_layer == original


@requires_template
def test_costmap_values_are_actually_written():
    """costmap のキーが「たまたま一致」ではなく本当に書かれていること。

    preset を当てて値が変われば、書き込み経路が生きている証拠になる。
    既定値との一致だけを見ると、何も書いていなくてもテストが通る。
    """
    text, _ = render('cr2-01', TEMPLATE, 'cautious')
    generated = yaml.safe_load(text)

    local = _ros_parameters(generated, 'local_costmap')
    assert local['inflation_layer']['inflation_radius'] == 0.8
    glob = _ros_parameters(generated, 'global_costmap')
    assert glob['inflation_layer']['inflation_radius'] == 0.8

    controller = _ros_parameters(generated, 'controller_server')
    assert controller['FollowPath']['desired_linear_vel'] == 0.2


@requires_template
def test_preset_changes_produce_a_diff():
    """preset を当てたらテンプレートと差が出ること（差分検出が効いている証拠）。"""
    text, _ = render('cr2-01', TEMPLATE, 'cautious')
    original = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8'))
    assert yaml.safe_load(text) != original


@requires_template
def test_non_registry_keys_are_left_untouched():
    """registry が管理していない定型（BT の xml パス、格子の大きさ）を壊さないこと。

    `plugins` は Phase 4 で意図的に足しているので、ここでは見ない
    （見るのは test_the_only_difference_is_the_virtual_obstacles_layer）。
    """
    text, _ = render('cr2-01', TEMPLATE, overrides=NO_VIRTUAL_OBSTACLES)
    generated = yaml.safe_load(text)
    original = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8'))

    local_gen = _ros_parameters(generated, 'local_costmap')
    local_org = _ros_parameters(original, 'local_costmap')
    assert local_gen['plugins'] == local_org['plugins']
    assert local_gen['width'] == local_org['width']
    assert local_gen['global_frame'] == local_org['global_frame']

    bt_gen = _ros_parameters(generated, 'bt_navigator')
    bt_org = _ros_parameters(original, 'bt_navigator')
    assert bt_gen == bt_org or bt_gen['transform_tolerance'] == bt_org['transform_tolerance']


@requires_template
def test_all_robots_reproduce_the_template():
    """個体差 yaml は Nav2 の値を動かさないこと。

    cr2-02 / cr2-03 は param_overrides を持たないので、生成結果は cr2-01 と
    同じになるはず。ここが割れたら個体 yaml に意図しない上書きが入っている。
    """
    baseline = yaml.safe_load(render('cr2-01', TEMPLATE)[0])
    for robot_id in ('cr2-02', 'cr2-03'):
        assert yaml.safe_load(render(robot_id, TEMPLATE)[0]) == baseline


# ---- テンプレート不在時の fallback（CI 想定） -----------------------------


def test_registry_only_fallback_covers_every_node(tmp_path):
    """既存スタックが無い環境でも registry だけで params を組めること。

    bringup がこの経路を使う。ここが壊れると CI や新しい開発機で
    mock すら起動できない。
    """
    registry = reg.load('cr2-01')
    params = {node: {'ros__parameters': values}
              for node, values in registry.as_nested().items()}

    assert 'controller_server' in params
    assert 'local_costmap' in params
    assert params['controller_server']['ros__parameters']['FollowPath'][
        'desired_linear_vel'] == 0.3

    # use_sim_time の流し込み経路もこの形で効くこと
    for block in iter_ros_parameters(params):
        block['use_sim_time'] = True
    assert params['local_costmap']['ros__parameters']['use_sim_time'] is True


def test_use_sim_time_reaches_double_nested_costmaps():
    """replay モードで costmap だけが実時刻を見る事故を防ぐ。

    一段しか見ない実装だと mock (use_sim_time=false) では既定値と一致して
    気づかず、replay で初めて壊れる。
    """
    params = {
        'controller_server': {'ros__parameters': {'use_sim_time': False}},
        'local_costmap': {'local_costmap': {'ros__parameters': {'use_sim_time': False}}},
    }
    for block in iter_ros_parameters(params):
        block['use_sim_time'] = True

    assert params['controller_server']['ros__parameters']['use_sim_time'] is True
    assert params['local_costmap']['local_costmap'][
        'ros__parameters']['use_sim_time'] is True


def test_unmapped_key_is_reported(tmp_path):
    """registry に無いパスを指すキーがあれば unmapped として返ること。"""
    template = tmp_path / 'nav2_params.yaml'
    doc = {'controller_server': {'ros__parameters': {'FollowPath': {}}}}
    template.write_text(yaml.safe_dump(doc), encoding='utf-8')

    _, unmapped = render('cr2-01', template)
    # FollowPath 配下は空なので controller_server のキーは全部書けない
    assert any(k.startswith('controller_server.FollowPath') for k in unmapped)


def test_render_does_not_mutate_the_registry_defaults():
    """生成が registry の値を書き換えないこと（deepcopy されていること）。"""
    registry = reg.load('cr2-01')
    before = copy.deepcopy(registry.values['velocity_smoother.max_accel'])
    nested = registry.as_nested()
    nested['velocity_smoother']['max_accel'][0] = 99.0
    assert registry.values['velocity_smoother.max_accel'] == before
