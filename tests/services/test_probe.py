"""`whill params probe` の純粋部分のテスト。

ROS の往復そのものは起動中のスタックが要るので CI では回せない。だが
「`ros2 param get` の出力をどう読むか」「試験値をどう作るか」は純粋関数なので
ここで固定する。実際に踏んだ壊れ方（DDS の警告を値として掴む、配列が
`array('d', [...])` で出る）を再発させない。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from whill_cli.probe import _close_enough, _format_value, _parse_get, _probe_value


@dataclass
class FakeSpec:
    type: str
    range: dict[str, Any] | None = None
    elements: list[dict[str, Any]] | None = None


# ---- ros2 param get の出力を読む ------------------------------------------


def test_parse_double():
    assert _parse_get('Double value is: 0.7', FakeSpec('double')) == 0.7


def test_parse_integer():
    assert _parse_get('Integer value is: 8765', FakeSpec('int')) == 8765


def test_parse_boolean():
    assert _parse_get('Boolean value is: True', FakeSpec('bool')) is True
    assert _parse_get('Boolean value is: False', FakeSpec('bool')) is False


def test_parse_double_array_in_python_array_form():
    """humble の `ros2 param get` は配列を array('d', [...]) で出す。

    そのまま json.loads すると落ちる。実際に踏んだ。
    """
    out = "Double values are: array('d', [0.3, 0.0, 1.0])"
    assert _parse_get(out, FakeSpec('double_array')) == [0.3, 0.0, 1.0]


def test_parse_ignores_dds_warning_lines():
    """CycloneDDS の警告が混ざっても値の行だけを読むこと。

    stdout と stderr を混ぜた実装で、警告文字列を値として掴んで
    float() に落ちた。行を選ぶことで防ぐ。
    """
    out = ('1789006683.215504 [0] ros2: enx00e04c6808dc: '
           'optional interface was not found.\n'
           'Double value is: 0.3')
    assert _parse_get(out, FakeSpec('double')) == 0.3


def test_parse_returns_none_when_no_value_line():
    assert _parse_get('Node not found', FakeSpec('double')) is None
    assert _parse_get('', FakeSpec('double')) is None


# ---- 試験値の作り方 --------------------------------------------------------


def test_probe_value_moves_within_range():
    spec = FakeSpec('double', {'min': 0.2, 'max': 1.5, 'step': 0.05})
    trial = _probe_value(spec, 0.6)
    assert trial != 0.6
    assert 0.2 <= trial <= 1.5


def test_probe_value_steps_down_at_upper_bound():
    """上限に張り付いている値でも動かせること。"""
    spec = FakeSpec('double', {'min': 0.2, 'max': 0.6, 'step': 0.05})
    trial = _probe_value(spec, 0.6)
    assert trial < 0.6
    assert trial >= 0.2


def test_probe_value_returns_same_when_range_is_a_single_point():
    """差動二輪の vy のように動かせない軸は「作れない」と分かること。

    同じ値を set しても反映の有無を判定できないので、無理に動かさない。
    """
    spec = FakeSpec('double', {'min': 0.0, 'max': 0.0, 'step': 0.05})
    assert _probe_value(spec, 0.0) == 0.0


def test_probe_value_for_bool_flips():
    assert _probe_value(FakeSpec('bool'), True) is False


def test_probe_value_for_array_uses_per_axis_ranges():
    """[vx, vy, vyaw] の vy は 0 固定。他の軸だけ動くこと。"""
    spec = FakeSpec('double_array', None, [
        {'label': 'ax', 'range': {'min': 0.05, 'max': 1.0, 'step': 0.05}},
        {'label': 'ay', 'range': {'min': 0.0, 'max': 0.0, 'step': 0.05}},
        {'label': 'ayaw', 'range': {'min': 0.2, 'max': 3.0, 'step': 0.1}},
    ])
    trial = _probe_value(spec, [0.3, 0.0, 1.0])
    assert trial[0] != 0.3
    assert trial[1] == 0.0
    assert trial[2] != 1.0


# ---- ros2 param set へ渡す形 ----------------------------------------------


def test_format_bool_is_lowercase():
    # Python の "True" では ros2 param set が受け取らない
    assert _format_value(True) == 'true'
    assert _format_value(False) == 'false'


def test_format_array_is_flow_style():
    assert _format_value([0.3, 0.0, 1.0]) == '[0.3, 0.0, 1.0]'


def test_format_scalar():
    assert _format_value(0.7) == '0.7'


# ---- 比較 ------------------------------------------------------------------


@pytest.mark.parametrize('a,b,expected', [
    (0.7, 0.7000000001, True),
    (0.7, 0.8, False),
    ([0.3, 0.0], [0.3, 0.0], True),
    ([0.3, 0.0], [0.3, 0.1], False),
    ([0.3], [0.3, 0.0], False),
    (True, True, True),
])
def test_close_enough(a, b, expected):
    assert _close_enough(a, b) is expected
