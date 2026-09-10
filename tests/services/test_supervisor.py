"""子プロセス管理のテスト。

ROS は要らない。`whill run` の代わりに python の短いスクリプトを走らせれば、
「出力を行単位で拾う」「グループごと確実に落とす」「終了コードを黙らない」が
全部確かめられる。CI の services ジョブで回る。

**プロセスグループごと落とせること**が一番大事。`ros2 launch` の子には
SIGINT が確実には伝播せず、孤児が生き残って次の起動と喧嘩する
（既存リポで実証済み）。そこをここで固める。
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import pytest

from whill_stackd.server import build_command
from whill_stackd.supervisor import State, Supervisor, SupervisorError


def py(script: str) -> list[str]:
    return [sys.executable, '-u', '-c', script]


async def wait_until(predicate, timeout: float = 10.0) -> bool:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


# ---- 起動と出力 ------------------------------------------------------------


async def test_captures_stdout_line_by_line():
    """まとめてではなく行ごとに拾うこと。

    UI のログ tail を「起動中にいま何が起きているか」が見えるものにするため。
    """
    lines = []
    sup = Supervisor(on_log=lambda line: lines.append(line))
    await sup.start(py('for i in range(3): print(f"line {i}")'))
    assert await wait_until(lambda: sup.state == State.STOPPED)

    assert [line.text for line in lines] == ['line 0', 'line 1', 'line 2']
    assert all(line.stream == 'stdout' for line in lines)


async def test_captures_stderr_separately():
    """stderr を stdout に混ぜない。警告か本当のエラーかを UI で区別する。"""
    lines = []
    sup = Supervisor(on_log=lambda line: lines.append(line))
    await sup.start(py('import sys; print("out"); print("err", file=sys.stderr)'))
    assert await wait_until(lambda: sup.state == State.STOPPED)

    streams = {line.text: line.stream for line in lines}
    assert streams == {'out': 'stdout', 'err': 'stderr'}


async def test_state_goes_running_then_stopped():
    states = []
    sup = Supervisor(on_state=states.append)
    await sup.start(py('pass'))
    assert await wait_until(lambda: sup.state == State.STOPPED)
    assert State.RUNNING in states
    assert states[-1] == State.STOPPED


# ---- 終了コード ------------------------------------------------------------


async def test_nonzero_exit_becomes_failed():
    """落ちたことを黙らない。"""
    sup = Supervisor()
    await sup.start(py('import sys; sys.exit(3)'))
    assert await wait_until(lambda: sup.state == State.FAILED)
    assert sup.exit_code == 3


async def test_clean_exit_is_stopped_not_failed():
    sup = Supervisor()
    await sup.start(py('pass'))
    assert await wait_until(lambda: sup.state == State.STOPPED)
    assert sup.exit_code == 0
    assert sup.state == State.STOPPED


async def test_missing_executable_is_reported():
    sup = Supervisor()
    with pytest.raises(SupervisorError, match='起動できない'):
        await sup.start(['/nonexistent/whill-run-xyz'])
    assert sup.state == State.FAILED


# ---- 二重起動 --------------------------------------------------------------


async def test_cannot_start_twice():
    """同じ個体に 2 セット起動するとノードが二重になる（既存リポで実証済み）。"""
    sup = Supervisor()
    await sup.start(py('import time; time.sleep(30)'))
    try:
        with pytest.raises(SupervisorError, match='既に'):
            await sup.start(py('pass'))
    finally:
        await sup.stop()


# ---- 停止 ------------------------------------------------------------------


async def test_stop_terminates_the_process():
    sup = Supervisor()
    await sup.start(py('import time; time.sleep(60)'))
    await sup.stop()
    assert sup.state == State.STOPPED


async def test_stop_is_idempotent():
    sup = Supervisor()
    await sup.start(py('pass'))
    assert await wait_until(lambda: sup.state == State.STOPPED)
    await sup.stop()
    await sup.stop()
    assert sup.state == State.STOPPED


async def test_stop_before_start_does_nothing():
    sup = Supervisor()
    assert await sup.stop() is None


async def test_stop_kills_the_whole_process_group():
    """**孫プロセスまで落ちること。**

    `ros2 launch` は driver や static_transform_publisher を子として持つ。
    親だけ落として孤児が残ると、次の起動でノードが二重になる。
    `process.send_signal` では親にしか届かないので、グループへ送る必要がある。

    ここでは「SIGINT を無視する孫」を作って、それでも落ちることを確かめる。
    """
    child_pid_file = None
    script = '''
import os, signal, subprocess, sys, tempfile, time
# SIGINT を無視する子を作る。ros2 launch の子が SIGINT を取りこぼす状況の模擬。
child = subprocess.Popen([sys.executable, "-u", "-c",
    "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
    "print('child ready', flush=True); time.sleep(120)"])
path = os.environ["CHILD_PID_FILE"]
with open(path, "w") as handle:
    handle.write(str(child.pid))
print("parent ready", flush=True)
time.sleep(120)
'''
    import tempfile
    with tempfile.NamedTemporaryFile('w+', delete=False) as handle:
        child_pid_file = handle.name

    lines = []
    sup = Supervisor(on_log=lambda line: lines.append(line.text))
    env = dict(os.environ, CHILD_PID_FILE=child_pid_file)
    await sup.start(py(script), env=env)

    assert await wait_until(lambda: 'parent ready' in lines and 'child ready' in lines)
    with open(child_pid_file) as handle:
        child_pid = int(handle.read().strip())
    assert _alive(child_pid), '孫プロセスが起動していない'

    await sup.stop()

    assert await wait_until(lambda: not _alive(child_pid), timeout=15.0), \
        '孫プロセスが生き残った（孤児になる）'
    os.unlink(child_pid_file)


async def test_stop_escalates_past_sigint(monkeypatch):
    """SIGINT を無視するプロセスでも確実に落ちること。

    段階を上げずに諦めると、止めたつもりのスタックが動き続ける。
    """
    import whill_stackd.supervisor as module
    monkeypatch.setattr(module, 'SIGINT_GRACE_SEC', 0.5)
    monkeypatch.setattr(module, 'SIGTERM_GRACE_SEC', 0.5)

    sup = Supervisor()
    await sup.start(py(
        'import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); '
        'signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)'))
    await asyncio.sleep(0.3)
    await sup.stop()
    assert sup.state == State.STOPPED
    assert sup.pid is None or not _alive(sup.pid)


# ---- 再起動 ----------------------------------------------------------------


async def test_restart_stops_then_starts():
    lines = []
    sup = Supervisor(on_log=lambda line: lines.append(line.text))
    await sup.start(py('import time; print("first", flush=True); time.sleep(60)'))
    assert await wait_until(lambda: 'first' in lines)

    await sup.restart(py('print("second", flush=True)'))
    assert await wait_until(lambda: 'second' in lines)
    assert await wait_until(lambda: sup.state == State.STOPPED)


# ---- ログの保持 ------------------------------------------------------------


async def test_recent_logs_are_kept_for_late_clients():
    """後から繋いだクライアントに直近を見せる。"""
    sup = Supervisor()
    await sup.start(py('for i in range(5): print(i)'))
    assert await wait_until(lambda: sup.state == State.STOPPED)
    assert [line.text for line in sup.recent_logs()] == ['0', '1', '2', '3', '4']
    assert [line.text for line in sup.recent_logs(2)] == ['3', '4']


async def test_log_buffer_is_bounded():
    """全部持つとメモリを食う。古すぎる行は役に立たない。"""
    from whill_stackd.supervisor import LOG_BUFFER_LINES
    sup = Supervisor()
    await sup.start(py(f'for i in range({LOG_BUFFER_LINES + 50}): print(i)'))
    assert await wait_until(lambda: sup.state == State.STOPPED, timeout=20.0)
    assert len(sup.recent_logs()) == LOG_BUFFER_LINES


# ---- status ----------------------------------------------------------------


async def test_status_reports_command_and_exit_code():
    sup = Supervisor()
    await sup.start(py('import sys; sys.exit(2)'))
    assert await wait_until(lambda: sup.state == State.FAILED)
    status = sup.status()
    assert status['state'] == 'failed'
    assert status['exit_code'] == 2
    assert status['command'][0] == sys.executable


# ---- コマンド組み立て ------------------------------------------------------


def test_build_command_defaults_to_gateway():
    """stackd から起動するときは gateway 込みが既定。

    Web から操作するための常駐サービスなので、gateway が無いと繋げない。
    """
    command = build_command('/repo', robot='cr2-01', mode='mock')
    assert '--gateway' in command
    assert command[:3] == ['uv', 'run', '--project']
    assert '/repo/services' in command


def test_build_command_passes_options():
    command = build_command('/repo', robot='cr2-02', mode='replay',
                            preset='cautious', bag='bags/x', camera=True)
    assert '--robot' in command and 'cr2-02' in command
    assert '--mode' in command and 'replay' in command
    assert '--preset' in command and 'cautious' in command
    assert '--bag' in command and 'bags/x' in command
    assert '--camera' in command


def test_build_command_omits_empty_options():
    command = build_command('/repo', robot='cr2-01', mode='mock', gateway=False)
    assert '--preset' not in command
    assert '--bag' not in command
    assert '--camera' not in command
    assert '--gateway' not in command


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
