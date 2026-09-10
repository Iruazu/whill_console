"""param 橋渡しのテスト。

ROS のサービス呼び出しそのものは起動中のスタックが要るので、ここでは
純粋な部分を固める:

  - 走行中判定（`locked_while_moving` の門番）
  - registry の値 ↔ rcl_interfaces の型変換
  - UI へ渡す spec の中身

走行中判定は時刻を注入できる形にしてある。実時間に依存すると、
安全に関わる判定のテストが不安定になる。
"""

from __future__ import annotations

import pytest
from rcl_interfaces.msg import ParameterType

from whill_gateway.param_bridge import (
    MOVING_CMD_EPS,
    MOVING_HOLD_SEC,
    MovingWatch,
    _close,
    _from_parameter_value,
    _to_parameter_value,
    spec_payload,
)
from whill_params import registry as reg


@pytest.fixture()
def specs():
    return reg.load_specs_only()


# ---- 走行中判定 ------------------------------------------------------------


def test_not_moving_before_any_command():
    assert MovingWatch().is_moving(100.0) is False


def test_moving_after_a_nonzero_command():
    watch = MovingWatch()
    watch.observe(0.3, 0.0, now=10.0)
    assert watch.is_moving(10.0) is True


def test_angular_only_counts_as_moving():
    """その場旋回中も走行中。速度上限を変えられたら危ない。"""
    watch = MovingWatch()
    watch.observe(0.0, 0.4, now=10.0)
    assert watch.is_moving(10.0) is True


def test_tiny_command_is_not_moving():
    watch = MovingWatch()
    watch.observe(MOVING_CMD_EPS / 2, 0.0, now=10.0)
    assert watch.is_moving(10.0) is False


def test_still_moving_within_the_hold_window():
    """`/cmd_vel` の publish が止まった瞬間を「停止した」と解釈しない。

    惰性で動いている最中に変更を許してしまう。
    """
    watch = MovingWatch()
    watch.observe(0.3, 0.0, now=10.0)
    assert watch.is_moving(10.0 + MOVING_HOLD_SEC * 0.9) is True


def test_stops_being_moving_after_the_hold_window():
    watch = MovingWatch()
    watch.observe(0.3, 0.0, now=10.0)
    assert watch.is_moving(10.0 + MOVING_HOLD_SEC * 1.1) is False


def test_zero_command_does_not_extend_the_window():
    watch = MovingWatch()
    watch.observe(0.3, 0.0, now=10.0)
    watch.observe(0.0, 0.0, now=10.5)
    assert watch.is_moving(10.0 + MOVING_HOLD_SEC * 1.1) is False


# ---- 型変換 ----------------------------------------------------------------


def test_double_roundtrip(specs):
    spec = specs['controller_server.FollowPath.desired_linear_vel']
    pv = _to_parameter_value(spec, 0.42)
    assert pv.type == ParameterType.PARAMETER_DOUBLE
    assert _from_parameter_value(pv) == pytest.approx(0.42)


def test_int_roundtrip(specs):
    spec = specs['whill_gateway.port']
    pv = _to_parameter_value(spec, 9000)
    assert pv.type == ParameterType.PARAMETER_INTEGER
    assert _from_parameter_value(pv) == 9000


def test_bool_roundtrip(specs):
    spec = specs['controller_server.FollowPath.use_rotate_to_heading']
    pv = _to_parameter_value(spec, False)
    assert pv.type == ParameterType.PARAMETER_BOOL
    assert _from_parameter_value(pv) is False


def test_string_roundtrip(specs):
    spec = specs['whill_gateway.bind_address']
    pv = _to_parameter_value(spec, '127.0.0.1')
    assert pv.type == ParameterType.PARAMETER_STRING
    assert _from_parameter_value(pv) == '127.0.0.1'


def test_double_array_roundtrip(specs):
    spec = specs['velocity_smoother.max_accel']
    pv = _to_parameter_value(spec, [0.3, 0.0, 1.0])
    assert pv.type == ParameterType.PARAMETER_DOUBLE_ARRAY
    assert _from_parameter_value(pv) == [0.3, 0.0, 1.0]


def test_double_accepts_int_input(specs):
    """yaml や JSON が 1 を int で渡してくることがある。"""
    spec = specs['controller_server.FollowPath.desired_linear_vel']
    pv = _to_parameter_value(spec, 1)
    assert _from_parameter_value(pv) == pytest.approx(1.0)


# ---- UI へ渡す spec --------------------------------------------------------


def test_spec_payload_carries_everything_the_ui_needs(specs):
    """ここに無いものは UI に出ない（ADR-0001）。"""
    spec = specs['controller_server.FollowPath.desired_linear_vel']
    payload = spec_payload(spec, 0.3, '/controller_server')
    for field in ('key', 'node', 'ros_node', 'name', 'type', 'value', 'default',
                  'range', 'unit', 'live', 'safety_class', 'description'):
        assert field in payload, f'{field} が欠けている'
    assert payload['safety_class'] == 'locked_while_moving'
    assert payload['ros_node'] == '/controller_server'


def test_spec_payload_carries_per_axis_elements(specs):
    """配列は軸ごとにスライダーを作る。elements が無いと組めない。"""
    spec = specs['velocity_smoother.max_accel']
    payload = spec_payload(spec, [0.3, 0.0, 1.0], '/velocity_smoother')
    assert payload['elements'] is not None
    assert [e['label'] for e in payload['elements']] == ['ax', 'ay', 'ayaw']


def test_spec_payload_uses_the_real_ros_node_name():
    """costmap は yaml のキーと ROS のノード名が違う（Phase 1 で実測）。"""
    registry = reg.load('cr2-01')
    spec = registry.spec('local_costmap.inflation_layer.inflation_radius')
    payload = spec_payload(spec, 0.6, registry.ros_node(spec.node))
    assert payload['ros_node'] == '/local_costmap/local_costmap'
    assert payload['node'] == 'local_costmap'


# ---- 値の比較 --------------------------------------------------------------


@pytest.mark.parametrize('a,b,expected', [
    (0.6, 0.6000000001, True),
    (0.6, 0.7, False),
    ([0.3, 0.0], [0.3, 0.0], True),
    ([0.3, 0.0], [0.3, 0.1], False),
    (True, True, True),
    # Python では True == 1 が成り立つ。素朴に比較すると
    # 「bool のはずが int が入っている」という本物の食い違いを見逃す。
    (True, 1, False),
    (1, True, False),
    ('a', 'a', True),
    (0.6, [0.6], False),
])
def test_close(a, b, expected):
    assert _close(a, b) is expected
