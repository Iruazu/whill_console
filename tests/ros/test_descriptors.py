"""ParameterDescriptor 生成のテスト。

gateway はこの descriptor を introspection してスライダーを作る。
範囲や説明が落ちると UI に何も出ないので、生成側で担保する。
"""

from __future__ import annotations

from whill_params import registry as reg
from whill_params.descriptors import descriptor_for


def test_double_gets_floating_point_range():
    specs = reg.load_specs_only()
    spec = specs['controller_server.FollowPath.desired_linear_vel']
    descriptor = descriptor_for(spec)
    assert descriptor.floating_point_range
    assert descriptor.floating_point_range[0].from_value == 0.05
    assert descriptor.floating_point_range[0].to_value == 1.0


def test_int_gets_integer_range():
    spec = reg.load_specs_only()['whill_gateway.port']
    descriptor = descriptor_for(spec)
    assert descriptor.integer_range
    assert descriptor.integer_range[0].from_value == 1024


def test_description_carries_unit_and_safety():
    spec = reg.load_specs_only()['controller_server.FollowPath.desired_linear_vel']
    text = descriptor_for(spec).description
    assert 'm/s' in text
    assert 'locked_while_moving' in text
    assert 'live' in text


def test_restart_required_is_visible_in_description():
    spec = reg.load_specs_only()['local_costmap.robot_radius']
    text = descriptor_for(spec).description
    assert 'restart required' in text


def test_descriptors_are_not_read_only():
    # live=false は「再起動が要る」であって読み取り専用ではない。read_only に
    # すると stackd の再起動込み適用フローまで塞がる。
    for spec in reg.load_specs_only().values():
        assert descriptor_for(spec).read_only is False
