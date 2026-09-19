"""実機の測定の道具（#78、Phase 7 の段 0〜2）。

**当日に道具のバグを踏まないために、実機の前にここで固める。**

`measure.py` は集計と判定を純関数に分けてあるので、gateway も ROS も
立てずに検証できる。
"""

from __future__ import annotations

import math

import pytest

from whill_cli import config, measure


def frame(*items, derived=(), expected=True):
    return {
        'type': 'telemetry',
        'drivers': [{'driver': 'whill_serial', 'expected': expected, 'items': list(items)}],
        'derived': list(derived),
        'stamp': 1.0,
    }


def item(name, value, *, level='ok', unit='A', driver='whill_serial'):
    return {'name': name, 'driver': driver, 'value': value, 'unit': unit, 'level': level}


# ---- 段 0: テレメトリ -------------------------------------------------------


def test_min_median_max_come_from_the_values_that_arrived():
    frames = [frame(item('battery', v)) for v in (90.0, 80.0, 70.0)]
    stats = measure.collect_telemetry(frames)
    assert stats['battery'].count == 3
    assert (stats['battery'].low, stats['battery'].median, stats['battery'].high) == \
        (70.0, 80.0, 90.0)


def test_missing_values_are_counted_not_treated_as_zero():
    """**「値が無い」と「0」を混ぜない。** 混ぜるとバッテリー 0 % に見える。"""
    frames = [frame(item('battery', None)), frame(item('battery', 50.0))]
    stats = measure.collect_telemetry(frames)
    assert stats['battery'].missing == 1
    assert stats['battery'].values == [50.0]
    assert stats['battery'].low == 50.0


def test_non_finite_values_are_missing_too():
    stats = measure.collect_telemetry([frame(item('temp', float('nan')))])
    assert stats['temp'].missing == 1
    assert stats['temp'].values == []


def test_levels_are_counted():
    frames = [frame(item('battery', 50.0, level='ok')),
              frame(item('battery', 20.0, level='warn'))]
    stats = measure.collect_telemetry(frames)
    assert stats['battery'].levels == {'ok': 1, 'warn': 1}


def test_derived_items_are_collected():
    stats = measure.collect_telemetry([frame(item('battery', 1.0),
                                             derived=[item('yaw_rate_vs_ndt', 0.4,
                                                           driver='derived')])])
    assert stats['yaw_rate_vs_ndt'].driver == 'derived'


def test_declaration_mismatch_is_split_by_cause():
    """原因が違うものを混ぜない（トピック名 / フィールド名 / そのモードに入力が無い）。"""
    stats = measure.collect_telemetry([frame(item('battery', 50.0), item('temp', None),
                                             item('surprise', 1.0))])
    diff = measure.compare_with_declaration(
        stats, {'battery': 'whill_serial', 'temp': 'whill_serial', 'missing': 'velodyne'})
    assert diff['never_arrived'] == ['missing']
    assert diff['no_value'] == ['temp']
    assert diff['undeclared'] == ['surprise']


def test_items_of_drivers_that_do_not_run_are_not_counted_as_faults():
    """gateway は起動していないドライバの項目も送る（expected: false）。

    これを「宣言に無いのに来た」「値が無い」と数えると、mock で毎回赤が出る。
    """
    stats = measure.collect_telemetry([frame(item('frame_rate', None, driver='realsense'),
                                             expected=False)])
    diff = measure.compare_with_declaration(stats, {})
    assert diff['undeclared'] == []
    assert diff['no_value'] == []


def test_derived_items_without_inputs_are_not_faults():
    """mock には scan-to-map localizer が居ないので yaw_rate_vs_ndt は出なくて当然。"""
    stats = measure.collect_telemetry([frame(item('battery', 1.0),
                                             derived=[item('yaw_rate_vs_ndt', None,
                                                           driver='derived',
                                                           level='unknown')])])
    diff = measure.compare_with_declaration(
        stats, {'battery': 'whill_serial', 'yaw_rate_vs_ndt': 'derived'},
        inputs_unavailable={'yaw_rate_vs_ndt'})
    assert diff['no_value'] == []
    assert diff['inputs_unavailable'] == ['yaw_rate_vs_ndt']


def test_mock_has_no_localizer_so_the_derived_item_is_excused():
    """宣言（inputs）から機械的に判定する。名前を並べない。"""
    assert 'yaw_rate_vs_ndt' in config.derived_without_inputs('mock')
    # 実機は localizer が居るので、出なければ故障
    assert 'yaw_rate_vs_ndt' not in config.derived_without_inputs('real')


def test_markdown_names_the_mismatches():
    stats = measure.collect_telemetry([frame(item('battery', 50.0))])
    text = measure.telemetry_markdown(
        stats, 10.0, {'never_arrived': ['scan_rate'], 'no_value': [],
                      'inputs_unavailable': [], 'undeclared': []})
    assert '| battery |' in text
    assert 'scan_rate' in text
    assert '5.0' not in text.split('\n')[0]          # 見出し行に数字が混ざらない


def test_markdown_says_so_when_nothing_is_wrong():
    stats = measure.collect_telemetry([frame(item('battery', 50.0))])
    text = measure.telemetry_markdown(
        stats, 1.0, {'never_arrived': [], 'no_value': [],
                     'inputs_unavailable': [], 'undeclared': []})
    assert '食い違いなし' in text


def test_declared_telemetry_comes_from_the_config():
    declared = config.declared_telemetry('cr2-01', 'mock')
    assert declared['battery'] == 'whill_serial'
    assert declared['scan_rate'] == 'velodyne'
    assert declared['yaw_rate_vs_ndt'] == 'derived'
    # realsense は既定で起動しない。mock の宣言に入れない
    assert 'frame_rate' not in declared


# ---- 段 1: 止まるまで -------------------------------------------------------


def test_twist_csv_is_read_as_vx_and_wz():
    assert measure.parse_twist_csv('0.25,0.0,0.0,0.0,0.0,-0.5') == (0.25, -0.5)


@pytest.mark.parametrize('line', ['', 'x', '1,2,3', 'a,b,c,d,e,f', '[WARN] something'])
def test_unreadable_lines_are_dropped(line):
    assert measure.parse_twist_csv(line) is None


def test_zero_and_moving_are_separate_judgements():
    assert measure.is_zero((0.0, 0.0))
    assert not measure.is_zero((0.0, 0.2))
    assert measure.is_moving((0.05, 0.0))
    # 浮動小数の残りカスをゼロとして扱う
    assert measure.is_zero((1e-9, -1e-9))
    assert not measure.is_moving((1e-9, 1e-9))


def test_summary_reports_median_max_and_failures():
    """**平均は出さない。** 知りたいのは最悪値と、止まらなかった回数。"""
    runs = [measure.StopRun('estop', 0.10), measure.StopRun('estop', 0.30),
            measure.StopRun('estop', None), measure.StopRun('heartbeat', 0.55)]
    summary = measure.summarize_stops(runs)
    assert summary['estop']['n'] == 3
    assert summary['estop']['failed'] == 1
    assert summary['estop']['median_ms'] == pytest.approx(200)
    assert summary['estop']['max_ms'] == pytest.approx(300)
    assert summary['heartbeat']['failed'] == 0


def test_summary_survives_a_trigger_that_never_stopped():
    summary = measure.summarize_stops([measure.StopRun('estop', None)])
    assert summary['estop']['failed'] == 1
    assert math.isnan(summary['estop']['median_ms'])


def test_command_topic_comes_from_the_declaration():
    """実ドライバが受けるトピック。ここを直書きすると実機で別の口を見る。"""
    assert config.command_topic() == '/whill/controller/cmd_vel'
