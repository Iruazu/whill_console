"""仮想障害物層の配線のテスト。

層そのものの振る舞い（円を塗る、消える）は起動中の costmap でしか
確かめられないので、ここで見るのは**配線が食い違っていないこと**。

一番起きやすい壊れ方は「C++ 側のクラス名を変えたのに生成側の文字列を
直し忘れる」で、これは起動して初めて `Failed to create` で分かる。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whill_params.generate_nav2_params import (
    VIRTUAL_OBSTACLES_PLUGIN,
    _insert_virtual_obstacles,
    _ros_parameters,
)


def _plugin_xml() -> Path | None:
    try:
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory('whill_costmap_plugins'))
    except Exception:  # noqa: BLE001 - 未ビルドの環境では skip する
        return None
    path = share / 'whill_costmap_plugins.xml'
    return path if path.is_file() else None


def test_generated_plugin_class_matches_the_registration():
    """生成側が書くクラス名と、pluginlib に登録した型が一致すること。

    食い違うと Nav2 が `Failed to create` で落ちる。起動して初めて
    分かるので、ここで止める。
    """
    xml = _plugin_xml()
    if xml is None:
        pytest.skip('whill_costmap_plugins が未ビルド')

    params: dict = {'global_costmap': {'global_costmap': {'ros__parameters': {
        'plugins': ['static_layer', 'inflation_layer'],
    }}}}
    _insert_virtual_obstacles(params, 'global_costmap')
    generated = _ros_parameters(params, 'global_costmap')[VIRTUAL_OBSTACLES_PLUGIN]['plugin']

    assert generated in xml.read_text(encoding='utf-8'), (
        f'{generated} が plugin xml に登録されていない')


def test_plugin_is_inserted_before_inflation():
    """**inflation_layer より前。** 後ろだと膨張がかからず、車体が入れない
    隙間を通る経路が出る。"""
    params: dict = {'local_costmap': {'local_costmap': {'ros__parameters': {
        'plugins': ['static_layer', 'obstacle_layer', 'inflation_layer'],
    }}}}
    _insert_virtual_obstacles(params, 'local_costmap')
    plugins = _ros_parameters(params, 'local_costmap')['plugins']
    assert plugins.index(VIRTUAL_OBSTACLES_PLUGIN) < plugins.index('inflation_layer')


def test_plugin_is_appended_when_there_is_no_inflation():
    params: dict = {'global_costmap': {'global_costmap': {'ros__parameters': {
        'plugins': ['static_layer'],
    }}}}
    _insert_virtual_obstacles(params, 'global_costmap')
    assert _ros_parameters(params, 'global_costmap')['plugins'][-1] == VIRTUAL_OBSTACLES_PLUGIN


def test_inserting_twice_does_not_duplicate():
    params: dict = {'global_costmap': {'global_costmap': {'ros__parameters': {
        'plugins': ['static_layer', 'inflation_layer'],
    }}}}
    _insert_virtual_obstacles(params, 'global_costmap')
    _insert_virtual_obstacles(params, 'global_costmap')
    plugins = _ros_parameters(params, 'global_costmap')['plugins']
    assert plugins.count(VIRTUAL_OBSTACLES_PLUGIN) == 1


def test_missing_plugins_list_is_left_alone():
    """plugins が無いノードには触らない。壊れたテンプレートで例外にしない。"""
    params: dict = {'map_server': {'ros__parameters': {'yaml_filename': 'x.yaml'}}}
    _insert_virtual_obstacles(params, 'map_server')
    assert 'plugins' not in params['map_server']['ros__parameters']


def test_layer_subscribes_the_topic_the_gateway_publishes():
    """gateway が publish するトピックと層が購読するトピックが一致すること。

    Phase 4 の #30 で gateway 側を書くときの契約。
    """
    params: dict = {'global_costmap': {'global_costmap': {'ros__parameters': {
        'plugins': ['inflation_layer'],
    }}}}
    _insert_virtual_obstacles(params, 'global_costmap')
    layer = _ros_parameters(params, 'global_costmap')[VIRTUAL_OBSTACLES_PLUGIN]
    assert layer['topic'] == '/whill/virtual_obstacles'


def test_registry_controls_whether_the_layer_is_added():
    """registry の bool で on/off できること（設計原則 3）。"""
    from whill_params import registry as reg

    registry = reg.load('cr2-01')
    assert registry.values['global_costmap.virtual_obstacles_enabled'] is True
    spec = registry.spec('global_costmap.virtual_obstacles_enabled')
    # 層の追加は構造の変更なので再起動が要る
    assert spec.live is False


def test_max_radius_is_bounded():
    """巨大な円で costmap が埋まらないよう、上限を持つこと。"""
    params: dict = {'global_costmap': {'global_costmap': {'ros__parameters': {
        'plugins': ['inflation_layer'],
    }}}}
    _insert_virtual_obstacles(params, 'global_costmap')
    layer = _ros_parameters(params, 'global_costmap')[VIRTUAL_OBSTACLES_PLUGIN]
    assert 0 < layer['max_radius'] <= 10.0


def test_plugin_xml_is_valid_yaml_free():
    """plugin xml が壊れていないこと（読めること）。"""
    xml = _plugin_xml()
    if xml is None:
        pytest.skip('whill_costmap_plugins が未ビルド')
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml.read_text(encoding='utf-8'))
    assert root.tag == 'class_libraries'
