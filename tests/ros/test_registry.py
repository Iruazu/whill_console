"""whill_params.registry のテスト。

ROS の実行環境が要る（whill_params が import できること）。
scripts/test.sh は ros/install/setup.bash を source してから走らせる。
"""

from __future__ import annotations

import pytest

from whill_params import registry as reg


@pytest.fixture()
def registry():
    return reg.load('cr2-01')


def test_defaults_are_within_their_own_ranges(registry):
    # 登録ミスの検出。default が range を外れていたら UI のスライダーが
    # 初期状態で範囲外を指す。
    for spec in registry.specs.values():
        spec.validate_value(spec.default)


def test_live_keys_are_a_subset(registry):
    assert set(registry.live_keys()) <= set(registry.specs)
    assert registry.live_keys(), 'live なパラメータが 1 つも無いのはおかしい'


def test_locked_param_is_rejected_while_moving(registry):
    key = 'controller_server.FollowPath.desired_linear_vel'
    assert registry.spec(key).safety_class == 'locked_while_moving'
    with pytest.raises(reg.RegistryError, match='走行中は変更できない'):
        registry.set_value(key, 0.4, moving=True)
    # 停止中なら通ること
    registry.set_value(key, 0.4, moving=False)
    assert registry.values[key] == 0.4


def test_out_of_range_is_rejected(registry):
    key = 'controller_server.FollowPath.min_lookahead_dist'
    with pytest.raises(reg.RegistryError, match='上限'):
        registry.set_value(key, 99.0)
    with pytest.raises(reg.RegistryError, match='下限'):
        registry.set_value(key, -1.0)


def test_wrong_type_is_rejected(registry):
    with pytest.raises(reg.RegistryError, match='型が'):
        registry.set_value('controller_server.FollowPath.lookahead_time', 'fast')


def test_bool_is_not_accepted_as_int(registry):
    # bool は int の派生。素通しすると port=True のような値が通る。
    with pytest.raises(reg.RegistryError):
        registry.set_value('whill_gateway.port', True)


def test_double_array_uses_per_axis_ranges(registry):
    key = 'velocity_smoother.max_accel'
    # vy 軸は差動二輪では 0 固定。全軸共通 range だと既定値すら通らない。
    registry.set_value(key, [0.3, 0.0, 1.0])
    with pytest.raises(reg.RegistryError, match=r'\[ax\]'):
        registry.set_value(key, [5.0, 0.0, 1.0])
    with pytest.raises(reg.RegistryError, match='要素数'):
        registry.set_value(key, [0.3, 0.0])


def test_unknown_key_is_rejected(registry):
    with pytest.raises(reg.RegistryError, match='未知のパラメータ'):
        registry.set_value('controller_server.no_such_param', 1.0)


def test_preset_applies_and_records_name():
    registry = reg.load('cr2-01', preset='cautious')
    assert registry.applied_preset == 'cautious'
    assert registry.values['controller_server.FollowPath.desired_linear_vel'] == 0.2
    # preset が触っていないキーは default のまま
    assert registry.values['controller_server.FollowPath.lookahead_time'] == 1.5


def test_campus_cruise_preset_matches_defaults():
    """「元に戻す」ボタンの実体なので、default と一致していること。"""
    plain = reg.load('cr2-01')
    cruise = reg.load('cr2-01', preset='campus-cruise')
    for key in (reg.load('cr2-01', preset='campus-cruise').specs):
        if key in cruise.values and key in plain.values:
            assert cruise.values[key] == plain.values[key], f'{key} が default と違う'


def test_as_nested_builds_nav2_shape(registry):
    nested = registry.as_nested()
    assert nested['controller_server']['FollowPath']['desired_linear_vel'] == 0.3
    assert nested['local_costmap']['inflation_layer']['inflation_radius'] == 0.6


def test_every_robot_loads():
    for robot_id in ('cr2-01', 'cr2-02', 'cr2-03'):
        assert reg.load(robot_id).robot['robot_id'] == robot_id
