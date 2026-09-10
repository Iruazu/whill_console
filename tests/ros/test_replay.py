"""bag 再生の進捗のテスト。

`replay.py` は rclpy に依存せず、時刻を全部引数で受け取るので、ROS を
立てずに決定的に検証できる。

見たいのは「止まっているのが分かること」。再生が終わったのに進捗が
進み続けたり、逆に一時停止と「その時刻に車体が止まっていた」が
区別できなかったりすると、bag を見る意味が薄れる。
"""

from __future__ import annotations

import textwrap

import pytest

from whill_gateway.replay import (
    RATE_WINDOW_SEC,
    STALL_AFTER_SEC,
    BagInfo,
    ReplayProgress,
    read_bag_info,
)

START = 1785478491.709657
DURATION = 235.081798


def progress() -> ReplayProgress:
    return ReplayProgress(BagInfo(path='/bags/x', start_sec=START,
                                  duration_sec=DURATION))


# ---- metadata の読み取り ----------------------------------------------------


METADATA = textwrap.dedent("""
    rosbag2_bagfile_information:
      version: 5
      duration:
        nanoseconds: 235081798969
      starting_time:
        nanoseconds_since_epoch: 1785478491709657463
      message_count: 54669
""")


def test_reads_start_and_duration(tmp_path):
    (tmp_path / 'metadata.yaml').write_text(METADATA, encoding='utf-8')
    info = read_bag_info(str(tmp_path))
    assert info is not None
    assert info.duration_sec == pytest.approx(235.0818, abs=1e-3)
    assert info.start_sec == pytest.approx(1785478491.7096, abs=1e-3)


def test_missing_metadata_returns_none(tmp_path):
    """進捗が出ないだけで再生自体は成り立つ。ここで落とさない。"""
    assert read_bag_info(str(tmp_path)) is None


def test_malformed_metadata_returns_none(tmp_path):
    (tmp_path / 'metadata.yaml').write_text('rosbag2_bagfile_information: 3\n',
                                            encoding='utf-8')
    assert read_bag_info(str(tmp_path)) is None


def test_metadata_without_duration_returns_none(tmp_path):
    (tmp_path / 'metadata.yaml').write_text(
        'rosbag2_bagfile_information:\n  version: 5\n', encoding='utf-8')
    assert read_bag_info(str(tmp_path)) is None


# ---- 進捗 ------------------------------------------------------------------


def test_nothing_is_known_before_the_first_clock():
    frame = progress().frame(wall_sec=100.0)
    assert frame['elapsed'] is None
    assert frame['playing'] is False
    # 全体長は metadata から出るので、1 通も来ていなくても分かる。
    assert frame['total'] == pytest.approx(235.08, abs=0.01)


def test_elapsed_is_measured_from_the_bag_start():
    prog = progress()
    prog.observe(START + 12.5, wall_sec=100.0)
    assert prog.elapsed() == pytest.approx(12.5)


def test_elapsed_never_goes_negative():
    """bag より古い stamp の /clock が 1 通混ざっても負の経過時間を出さない。"""
    prog = progress()
    prog.observe(START - 5.0, wall_sec=100.0)
    assert prog.elapsed() == 0.0


def test_playing_while_the_clock_advances():
    prog = progress()
    prog.observe(START + 1.0, wall_sec=100.0)
    assert prog.playing(wall_sec=100.5) is True


def test_stalled_when_the_clock_stops():
    """一時停止と再生終了はどちらもこれで拾う。"""
    prog = progress()
    prog.observe(START + 1.0, wall_sec=100.0)
    assert prog.playing(wall_sec=100.0 + STALL_AFTER_SEC + 0.1) is False


def test_repeated_clock_values_do_not_count_as_progress():
    """player が同じ時刻を出し続けても「再生中」にしない。

    これを見落とすと、一時停止が永久に「再生中」と出る。
    """
    prog = progress()
    prog.observe(START + 1.0, wall_sec=100.0)
    prog.observe(START + 1.0, wall_sec=101.5)
    assert prog.playing(wall_sec=101.6) is False


def test_backwards_clock_is_ignored():
    prog = progress()
    prog.observe(START + 10.0, wall_sec=100.0)
    prog.observe(START + 3.0, wall_sec=100.1)
    assert prog.elapsed() == pytest.approx(10.0)


# ---- 再生速度 ---------------------------------------------------------------


def test_rate_needs_two_samples():
    prog = progress()
    prog.observe(START + 1.0, wall_sec=100.0)
    assert prog.rate(wall_sec=100.0) is None


def test_rate_is_one_at_realtime():
    prog = progress()
    for i in range(11):
        prog.observe(START + i * 0.1, wall_sec=100.0 + i * 0.1)
    assert prog.rate(wall_sec=101.0) == pytest.approx(1.0, abs=0.01)


def test_rate_is_two_at_double_speed():
    prog = progress()
    for i in range(11):
        prog.observe(START + i * 0.2, wall_sec=100.0 + i * 0.1)
    assert prog.rate(wall_sec=101.0) == pytest.approx(2.0, abs=0.01)


def test_rate_reflects_what_actually_happened_not_what_was_asked():
    """指令値ではなく観測値を出す。

    実機PC が重ければ 1.0 倍の指令でも実際は遅れる。指令値を出すと
    「速い/遅い」の判断を誤る。
    """
    prog = progress()
    for i in range(11):
        prog.observe(START + i * 0.05, wall_sec=100.0 + i * 0.1)
    assert prog.rate(wall_sec=101.0) == pytest.approx(0.5, abs=0.01)


def test_rate_is_unknown_while_stopped():
    """「停止中 1.0x」という矛盾した表示を出さない。

    窓は `/clock` が来たときにしか更新されないので、素直に計算すると
    一時停止した瞬間の速度が残り続ける。実機の bag で実際にそう出た。
    """
    prog = progress()
    for i in range(11):
        prog.observe(START + i * 0.1, wall_sec=100.0 + i * 0.1)
    assert prog.rate(wall_sec=101.0) == pytest.approx(1.0, abs=0.01)
    assert prog.rate(wall_sec=101.0 + STALL_AFTER_SEC + 0.1) is None


def test_old_samples_leave_the_window():
    prog = progress()
    prog.observe(START + 0.0, wall_sec=100.0)
    # 窓を跨いで倍速に切り替わる。古い等速の区間が残っていると
    # 速度が中間値に見えてしまう。
    for i in range(1, 11):
        wall = 100.0 + RATE_WINDOW_SEC + i * 0.1
        prog.observe(START + RATE_WINDOW_SEC + i * 0.2, wall_sec=wall)
    assert prog.rate(wall_sec=100.0 + RATE_WINDOW_SEC + 1.0) == pytest.approx(
        2.0, abs=0.01)


# ---- フレーム ---------------------------------------------------------------


def test_frame_reports_finished_at_the_end():
    prog = progress()
    prog.observe(START + DURATION, wall_sec=100.0)
    frame = prog.frame(wall_sec=100.0 + STALL_AFTER_SEC + 0.1)
    assert frame['playing'] is False
    assert frame['finished'] is True


def test_a_pause_in_the_middle_is_not_finished():
    """止まっているのが「一時停止」なのか「終わった」のかを区別する。"""
    prog = progress()
    prog.observe(START + 30.0, wall_sec=100.0)
    frame = prog.frame(wall_sec=100.0 + STALL_AFTER_SEC + 0.1)
    assert frame['playing'] is False
    assert frame['finished'] is False


def test_running_playback_is_not_finished():
    prog = progress()
    prog.observe(START + DURATION, wall_sec=100.0)
    assert prog.frame(wall_sec=100.1)['finished'] is False


def test_frame_without_metadata_has_no_total():
    """全体長が不明なとき、進捗バーを 0 % で描かせない。"""
    prog = ReplayProgress(None)
    prog.observe(START + 5.0, wall_sec=100.0)
    frame = prog.frame(wall_sec=100.1)
    assert frame['total'] is None
    assert frame['elapsed'] is None
    assert frame['finished'] is False


def test_frame_type_is_a_server_frame_and_control_is_a_client_frame():
    """状態と操作で名前を分けていること。"""
    from whill_gateway import protocol

    assert protocol.MSG_REPLAY in protocol.SERVER_MESSAGES
    assert protocol.MSG_REPLAY in protocol.DEFAULT_STREAMS
    assert protocol.MSG_REPLAY_CONTROL in protocol.CLIENT_MESSAGES
    assert progress().frame(wall_sec=1.0)['type'] == protocol.MSG_REPLAY


def test_seek_is_not_an_accepted_action():
    """やらないと決めたもの。定数に残して議論を繰り返さない（ADR-0004）。"""
    from whill_gateway import protocol

    assert 'seek' not in protocol.REPLAY_ACTIONS
    assert protocol.REPLAY_ACTIONS == {'pause', 'resume', 'set_rate'}
