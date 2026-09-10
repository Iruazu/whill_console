"""手動操作と E-stop の状態機械のテスト。

Phase 2 の受け入れ条件「ハートビート断で手動速度指令がゼロになることを
pytest で確認」がここ。

時刻はすべて注入する。実時間に依存させると、安全に関わるテストが
「たまに落ちるから再実行」になり、結局誰も見なくなる。
"""

from __future__ import annotations

import pytest

from whill_gateway.safety import ManualControl

TIMEOUT = 0.5
HOLD = 2.0


@pytest.fixture()
def control():
    return ManualControl(heartbeat_timeout=TIMEOUT, zero_hold=HOLD)


# ---- 何もしていない状態 ----------------------------------------------------


def test_idle_publishes_nothing(control):
    """手動操作を始めていないのに teleop スロットを掴まないこと。

    掴むと Nav2 の指令を邪魔する（twist_mux で優先度 50 > 10）。
    """
    out = control.output(0.0)
    assert out.publish is False
    assert out.reason == 'idle'


def test_heartbeat_alone_does_not_engage(control):
    """手動操作を始めていないクライアントのハートビートでは掴まない。"""
    control.heartbeat(0.0)
    assert control.output(0.0).publish is False


# ---- 正常な手動操作 --------------------------------------------------------


def test_command_is_passed_through(control):
    control.command(0.3, -0.2, now=0.0)
    out = control.output(0.0)
    assert out.publish is True
    assert (out.vx, out.wz) == (0.3, -0.2)
    assert out.reason == 'manual'


def test_command_counts_as_a_heartbeat(control):
    """指令そのものが生存通知を兼ねること。

    別々にすると、指令だけ届いてハートビートが落ちたときに
    「動かしているのに停止扱い」になる。
    """
    control.command(0.3, 0.0, now=0.0)
    assert control.output(TIMEOUT * 0.9).reason == 'manual'


def test_heartbeat_extends_the_session(control):
    control.command(0.3, 0.0, now=0.0)
    control.heartbeat(now=0.4)
    out = control.output(0.4 + TIMEOUT * 0.9)
    assert out.reason == 'manual'
    assert out.vx == 0.3


# ---- ハートビート断（受け入れ条件） ----------------------------------------


def test_zero_after_heartbeat_timeout(control):
    """**Phase 2 の受け入れ条件。** ハートビート断で速度ゼロになること。"""
    control.command(0.5, 0.3, now=0.0)
    out = control.output(TIMEOUT + 0.01)
    assert out.publish is True
    assert (out.vx, out.wz) == (0.0, 0.0)
    assert out.reason == 'heartbeat_lost'


def test_zero_is_published_continuously_not_once(control):
    """ゼロを 1 回出して黙らないこと。

    下流が最後の値を保持していると「ゼロを送ったのに動き続ける」ことになる。
    """
    control.command(0.5, 0.0, now=0.0)
    for t in (TIMEOUT + 0.01, TIMEOUT + 0.5, TIMEOUT + 1.0, TIMEOUT + HOLD):
        out = control.output(t)
        assert out.publish is True, f't={t} で publish が止まった'
        assert (out.vx, out.wz) == (0.0, 0.0)


def test_slot_is_released_after_the_hold(control):
    """十分ゼロを出したらスロットを手放し、Nav2 に戻すこと。

    掴んだままだと、操作者が手を離しても自律走行が再開できない。
    既存 twist_mux の teleop も同じ考え方（入力タイムアウトで落ちる）。
    """
    control.command(0.5, 0.0, now=0.0)
    control.output(TIMEOUT + 0.01)
    out = control.output(TIMEOUT + HOLD + 0.01)
    assert out.publish is False
    assert out.reason == 'idle'


def test_hold_is_longer_than_twist_mux_timeout():
    """既存 twist_mux の入力タイムアウト 0.5 s より長いこと。

    短いと、gateway が黙るのと twist_mux がスロットを落とすのが競合し、
    Nav2 の指令が一瞬だけ通り抜ける隙ができる。
    """
    from whill_gateway.safety import DEFAULT_ZERO_HOLD
    assert DEFAULT_ZERO_HOLD > 0.5


def test_recovering_heartbeat_resumes_control(control):
    """断のあとに繋がり直したら、また動かせること。"""
    control.command(0.5, 0.0, now=0.0)
    assert control.output(TIMEOUT + 0.01).reason == 'heartbeat_lost'
    control.command(0.2, 0.0, now=TIMEOUT + 0.2)
    out = control.output(TIMEOUT + 0.2)
    assert out.reason == 'manual'
    assert out.vx == 0.2


def test_stale_is_true_before_any_command(control):
    assert control.stale(0.0) is True


# ---- 明示的な終了 ----------------------------------------------------------


def test_release_stops_publishing(control):
    control.command(0.3, 0.0, now=0.0)
    control.release()
    assert control.output(0.0).publish is False


def test_release_clears_the_command(control):
    """解除後に古い速度が復活しないこと。"""
    control.command(0.3, 0.0, now=0.0)
    control.release()
    control.command(0.0, 0.0, now=1.0)
    assert control.output(1.0).vx == 0.0


# ---- E-stop ----------------------------------------------------------------


def test_estop_publishes_zero(control):
    control.engage_estop(now=0.0)
    out = control.output(0.0)
    assert out.publish is True
    assert (out.vx, out.wz) == (0.0, 0.0)
    assert out.reason == 'estop'


def test_estop_overrides_an_active_manual_command(control):
    control.command(0.5, 0.3, now=0.0)
    control.engage_estop(now=0.1)
    out = control.output(0.1)
    assert (out.vx, out.wz) == (0.0, 0.0)
    assert out.reason == 'estop'


def test_estop_never_times_out(control):
    """解除するまでゼロを出し続けること。時間で自動解除しない。"""
    control.engage_estop(now=0.0)
    for t in (1.0, 60.0, 3600.0):
        out = control.output(t)
        assert out.publish is True
        assert out.reason == 'estop'


def test_estop_survives_heartbeat_loss(control):
    """ハートビートが切れても E-stop は解けないこと。"""
    control.command(0.5, 0.0, now=0.0)
    control.engage_estop(now=0.1)
    out = control.output(0.1 + TIMEOUT + HOLD + 10.0)
    assert out.reason == 'estop'
    assert out.publish is True


def test_release_estop_does_not_resume_motion(control):
    """解除した瞬間に古い速度で走り出さないこと。

    E-stop の解除は「止めるのをやめる」であって「再開する」ではない。
    """
    control.command(0.5, 0.3, now=0.0)
    control.engage_estop(now=0.1)
    control.release_estop()
    out = control.output(0.2)
    assert out.publish is False
    assert out.reason == 'idle'


def test_manual_after_release_estop_works(control):
    control.engage_estop(now=0.0)
    control.release_estop()
    control.command(0.2, 0.0, now=1.0)
    out = control.output(1.0)
    assert out.reason == 'manual'
    assert out.vx == 0.2


def test_estop_flag_is_visible(control):
    assert control.estop is False
    control.engage_estop(now=0.0)
    assert control.estop is True
    control.release_estop()
    assert control.estop is False


# ---- 「切断されても止まる」の中身 ------------------------------------------


def test_disconnect_without_notice_still_zeroes(control):
    """切断イベントが来ない切れ方（電源断、Wi-Fi 消失）でも止まること。

    gateway 側は何も知らされない。時間が経つだけでゼロになる、という
    性質がここで担保される。
    """
    control.command(0.6, 0.0, now=0.0)
    # 以後、command も heartbeat も release も一切呼ばれない
    assert control.output(TIMEOUT + 0.01).vx == 0.0
    assert control.output(TIMEOUT + 0.01).publish is True
