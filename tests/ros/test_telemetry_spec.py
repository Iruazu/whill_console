"""telemetry 宣言の解決と閾値判定のテスト。

`telemetry_spec.py` は rclpy に依存せず、時刻を全部引数で受け取るので、ROS を
立てずに決定的に検証できる。

見たいのは 2 つ:

  1. **「値が無い」が 0 に化けないこと。** バッテリー 0 % と「バッテリー不明」を
     同じ絵にするのが、この画面で作りうる一番まずい誤読
  2. **`__rate` が宣言値ではなく実測を返すこと。** 宣言値を返す実装は
     「宣言 10 Hz なのに実際は 4 Hz」を見つけるという目的を反転させる
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from whill_gateway.telemetry_spec import (
    LEVEL_CRIT,
    LEVEL_OK,
    LEVEL_STALE,
    LEVEL_UNKNOWN,
    LEVEL_WARN,
    MIN_STALE_SEC,
    RATE_WINDOW_SEC,
    TelemetryError,
    TelemetrySpec,
    TelemetryStore,
    expected_drivers,
    extract,
    load_specs,
    level_of,
)

BASE = {
    'drivers': {
        'whill_serial': {
            'mock_node': 'mock_whill_serial',
            'publishes': [
                {'topic': '/whill/states/model_cr2',
                 'type': 'whill_msgs/msg/ModelCr2State', 'rate_hz': 2.5},
            ],
            'telemetry': [
                {'name': 'battery', 'topic': '/whill/states/model_cr2',
                 'field': 'battery_power', 'unit': '%', 'widget': 'bar',
                 'warn': 30, 'crit': 15, 'compare': 'below'},
                {'name': 'motor_current_left', 'topic': '/whill/states/model_cr2',
                 'field': 'left_motor_current', 'unit': 'A', 'widget': 'number',
                 'warn': 8.0, 'crit': 12.0, 'compare': 'above'},
            ],
        },
        'velodyne': {
            'mock_node': 'mock_velodyne',
            'publishes': [
                {'topic': '/velodyne_points',
                 'type': 'sensor_msgs/msg/PointCloud2', 'rate_hz': 10.0},
            ],
            'telemetry': [
                {'name': 'scan_rate', 'topic': '/velodyne_points',
                 'field': '__rate', 'unit': 'Hz', 'widget': 'number',
                 'warn': 8.0, 'crit': 5.0, 'compare': 'below'},
            ],
        },
    },
    'modes': {
        'mock': {'drivers': ['whill_serial', 'velodyne'], 'use_sim_time': False},
        'replay': {'drivers': [], 'use_sim_time': True},
    },
}


def store(robot=None, mode='mock') -> TelemetryStore:
    specs = load_specs(BASE, robot)
    return TelemetryStore(specs, expected_drivers(BASE, mode))


def spec(**over) -> TelemetrySpec:
    fields = dict(name='x', driver='d', topic='/t', field='f', widget='number',
                  warn=None, crit=None, compare='none')
    fields.update(over)
    return TelemetrySpec(**fields)


# ---- 宣言の読み取り ---------------------------------------------------------


def test_specs_come_from_the_declaration():
    names = [s.name for s in load_specs(BASE)]
    assert names == ['battery', 'motor_current_left', 'scan_rate']


def test_declared_rate_is_carried_over_from_publishes():
    """宣言レートは stale までの猶予を決めるためだけに持つ。"""
    battery = next(s for s in load_specs(BASE) if s.name == 'battery')
    assert battery.rate_hz == 2.5


def test_duplicate_names_are_rejected():
    """上書きのキーが平坦な名前空間なので、重複すると効き先が分からなくなる。"""
    base = {'drivers': {
        'a': {'publishes': [{'topic': '/t', 'type': 'x/msg/Y'}],
              'telemetry': [{'name': 'temp', 'topic': '/t', 'field': 'v',
                             'widget': 'number'}]},
        'b': {'publishes': [{'topic': '/u', 'type': 'x/msg/Y'}],
              'telemetry': [{'name': 'temp', 'topic': '/u', 'field': 'v',
                             'widget': 'number'}]},
    }}
    with pytest.raises(TelemetryError, match='重複'):
        load_specs(base)


def test_unknown_pseudo_field_is_rejected():
    """typo した疑似フィールドは「宣言したのに永久に値が出ない」になる。"""
    base = {'drivers': {'a': {
        'publishes': [{'topic': '/t', 'type': 'x/msg/Y'}],
        'telemetry': [{'name': 'r', 'topic': '/t', 'field': '__ratee',
                       'widget': 'number'}]}}}
    with pytest.raises(TelemetryError, match='疑似フィールド'):
        load_specs(base)


# ---- 個体ごとの上書き -------------------------------------------------------


def test_overrides_change_thresholds():
    specs = load_specs(BASE, {'telemetry_overrides': {'battery': {'warn': 40}}})
    battery = next(s for s in specs if s.name == 'battery')
    assert battery.warn == 40.0
    assert battery.crit == 15  # 触っていないほうは元のまま


def test_override_of_unknown_name_is_an_error():
    """黙って無視すると、typo した上書きが「書いたのに効かない」まま残る。"""
    with pytest.raises(TelemetryError, match='一致しない'):
        load_specs(BASE, {'telemetry_overrides': {'batery': {'warn': 40}}})


def test_only_thresholds_can_be_overridden():
    """topic や field を個体で差し替えると「同型 3 台」の前提が崩れる。"""
    with pytest.raises(TelemetryError, match='上書きできない'):
        load_specs(BASE, {'telemetry_overrides': {'battery': {'topic': '/other'}}})


def test_empty_overrides_is_fine():
    # cr2-01.yaml の既定がこれ
    assert load_specs(BASE, {'telemetry_overrides': {}})


# ---- 閾値 -------------------------------------------------------------------


@pytest.mark.parametrize('value,expected', [
    (87.0, LEVEL_OK), (31.0, LEVEL_OK), (30.0, LEVEL_WARN),
    (16.0, LEVEL_WARN), (15.0, LEVEL_CRIT), (0.0, LEVEL_CRIT),
])
def test_below_comparison(value, expected):
    assert level_of(value, spec(warn=30, crit=15, compare='below')) == expected


@pytest.mark.parametrize('value,expected', [
    (1.0, LEVEL_OK), (7.9, LEVEL_OK), (8.0, LEVEL_WARN),
    (11.9, LEVEL_WARN), (12.0, LEVEL_CRIT),
])
def test_above_comparison(value, expected):
    assert level_of(value, spec(warn=8.0, crit=12.0, compare='above')) == expected


def test_compare_none_is_always_ok():
    """speed_mode のように閾値を持たないもの。"""
    assert level_of(999.0, spec(compare='none')) == LEVEL_OK


def test_only_warn_declared():
    s = spec(warn=8.0, crit=None, compare='above')
    assert level_of(9.0, s) == LEVEL_WARN
    assert level_of(7.0, s) == LEVEL_OK


# ---- 値の取り出し -----------------------------------------------------------


def test_extract_reads_a_field():
    assert extract(SimpleNamespace(battery_power=87), 'battery_power') == 87.0


def test_extract_reads_a_nested_field():
    msg = SimpleNamespace(header=SimpleNamespace(seq=12))
    assert extract(msg, 'header.seq') == 12.0


def test_extract_returns_none_for_a_missing_field():
    """宣言と実メッセージの食い違いで gateway を落とさない。

    テレメトリ 1 件のために落とすと、E-stop も俯瞰図も一緒に止まる。
    level が unknown のまま動かないことで気づける。
    """
    assert extract(SimpleNamespace(a=1), 'nope') is None
    assert extract(SimpleNamespace(a=SimpleNamespace()), 'a.b.c') is None


def test_extract_rejects_non_numeric():
    assert extract(SimpleNamespace(name='hello'), 'name') is None


def test_extract_rejects_bool():
    """bool は int の派生。状態フラグに数値の顔をさせない。"""
    assert extract(SimpleNamespace(ok=True), 'ok') is None


def test_yaw_deg_from_quaternion():
    # z 軸まわり 90 度
    q = SimpleNamespace(x=0.0, y=0.0, z=math.sin(math.pi / 4), w=math.cos(math.pi / 4))
    assert extract(SimpleNamespace(orientation=q), '__yaw_deg') == pytest.approx(90.0)


def test_yaw_deg_without_orientation():
    assert extract(SimpleNamespace(a=1), '__yaw_deg') is None


# ---- 保持と level -----------------------------------------------------------


def test_nothing_received_is_unknown_not_zero():
    """バッテリー 0 % と「バッテリー不明」を同じ絵にしない。"""
    item = _find(store().frame(100.0), 'battery')
    assert item['value'] is None
    assert item['level'] == LEVEL_UNKNOWN
    assert item['age'] is None


def test_a_received_value_is_levelled():
    s = store()
    s.observe_topic('/whill/states/model_cr2', 100.0)
    s.set_value('battery', 87.0, 100.0)
    item = _find(s.frame(100.1), 'battery')
    assert item['value'] == 87.0
    assert item['level'] == LEVEL_OK
    assert item['age'] == pytest.approx(0.1)


def test_low_battery_crosses_warn_then_crit():
    s = store()
    s.set_value('battery', 25.0, 100.0)
    assert _find(s.frame(100.0), 'battery')['level'] == LEVEL_WARN
    s.set_value('battery', 10.0, 101.0)
    assert _find(s.frame(101.0), 'battery')['level'] == LEVEL_CRIT


def test_a_value_that_stops_arriving_goes_stale_but_keeps_its_value():
    """値を消すと「不明」と区別が付かない。薄く出して古さを添える。"""
    s = store()
    s.set_value('battery', 87.0, 100.0)
    item = _find(s.frame(100.0 + MIN_STALE_SEC + 0.1), 'battery')
    assert item['level'] == LEVEL_STALE
    assert item['value'] == 87.0
    assert item['age'] == pytest.approx(MIN_STALE_SEC + 0.1)


def test_nan_is_not_treated_as_a_received_value():
    """壊れたセンサが ok に見えないようにする。"""
    s = store()
    s.set_value('battery', float('nan'), 100.0)
    assert _find(s.frame(100.0), 'battery')['level'] == LEVEL_UNKNOWN


def test_stale_window_scales_with_the_declared_rate_but_has_a_floor():
    """100 Hz のトピックで 5/rate をそのまま使うと 0.05 s になり点滅する。"""
    assert spec().stale_after == MIN_STALE_SEC
    assert TelemetrySpec(name='a', driver='d', topic='/t', field='f',
                         widget='number', rate_hz=100.0).stale_after == MIN_STALE_SEC
    assert TelemetrySpec(name='a', driver='d', topic='/t', field='f',
                         widget='number', rate_hz=0.5).stale_after == 10.0


# ---- __rate -----------------------------------------------------------------


def test_rate_is_measured_not_declared():
    """宣言 10 Hz のトピックが実際に 4 Hz なら 4 を返すこと。

    宣言値を返す実装はこの指標の目的を反転させる。
    """
    s = store()
    for i in range(9):
        s.observe_topic('/velodyne_points', 100.0 + i * 0.25)
    item = _find(s.frame(102.0), 'scan_rate')
    assert item['value'] == pytest.approx(4.0, abs=0.01)
    # 宣言は 10 Hz、閾値は warn 8 / crit 5 の below なので crit
    assert item['level'] == LEVEL_CRIT


def test_rate_at_the_declared_speed_is_ok():
    s = store()
    for i in range(41):
        s.observe_topic('/velodyne_points', 100.0 + i * 0.1)
    assert _find(s.frame(104.0), 'scan_rate')['value'] == pytest.approx(10.0, abs=0.1)


def test_rate_of_a_dead_topic_is_zero_not_unknown():
    """velodyne が落ちたときに見たいのは「不明」ではなく「0 Hz で crit」。

    unknown にすると、一番気づきたい故障が一番目立たない色になる。
    """
    s = store()
    for i in range(5):
        s.observe_topic('/velodyne_points', 100.0 + i * 0.1)
    item = _find(s.frame(100.0 + RATE_WINDOW_SEC + 1.0), 'scan_rate')
    assert item['value'] == 0.0
    assert item['level'] == LEVEL_CRIT


def test_rate_of_a_topic_never_seen_is_unknown():
    item = _find(store().frame(100.0), 'scan_rate')
    assert item['value'] is None
    assert item['level'] == LEVEL_UNKNOWN


# ---- フレーム ---------------------------------------------------------------


def test_frame_groups_by_driver():
    frame = store().frame(100.0)
    assert [d['driver'] for d in frame['drivers']] == ['whill_serial', 'velodyne']
    assert [i['name'] for i in frame['drivers'][0]['items']] == [
        'battery', 'motor_current_left']


def test_expected_follows_the_mode():
    """「値が無い」と「そもそも起動していない」を区別するための旗。"""
    assert expected_drivers(BASE, 'mock') == {'whill_serial', 'velodyne'}
    assert expected_drivers(BASE, 'replay') == set()
    frame = store(mode='replay').frame(100.0)
    assert all(d['expected'] is False for d in frame['drivers'])


def test_frame_type_is_a_server_frame():
    from whill_gateway import protocol

    assert protocol.MSG_TELEMETRY in protocol.SERVER_MESSAGES
    assert protocol.MSG_TELEMETRY in protocol.STREAMS
    assert protocol.MSG_TELEMETRY in protocol.DEFAULT_STREAMS
    assert store().frame(1.0)['type'] == protocol.MSG_TELEMETRY


# ---- 実際の宣言に対して -----------------------------------------------------


def test_the_real_declaration_loads():
    """`config/robots/cr2-base.yaml` がそのまま読めること。

    宣言を足したときに、重複や疑似フィールドの typo をここで捕まえる。
    """
    from whill_params import registry as reg

    root = reg.config_root()
    import yaml
    base = yaml.safe_load((root / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
    robot = yaml.safe_load((root / 'robots' / 'cr2-01.yaml').read_text('utf-8'))
    specs = load_specs(base, robot)
    assert {s.name for s in specs} >= {'battery', 'yaw', 'temp', 'scan_rate'}


def test_every_telemetry_topic_is_declared_in_publishes():
    """型が分からないと購読できない。宣言だけあって値が出ない状態を作らない。"""
    from whill_params import registry as reg

    import yaml
    base = yaml.safe_load(
        (reg.config_root() / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
    published = {entry['topic']
                 for decl in base['drivers'].values()
                 for entry in (decl.get('publishes') or [])}
    for spec_ in load_specs(base):
        assert spec_.topic in published, f'{spec_.name} の {spec_.topic}'


def _find(frame: dict, name: str) -> dict:
    for driver in frame['drivers']:
        for item in driver['items']:
            if item['name'] == name:
                return item
    raise AssertionError(f'{name} がフレームに無い')
