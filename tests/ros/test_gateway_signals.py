"""gateway が止まる合図で、自分で、きれいに止まること（#65）。

以前は SIGTERM を受けても止まらず、port を握ったまま残った（systemd の stop が
SIGTERM）。rclpy のシグナル handler が ROS の context を落とすだけで、WebSocket
サーバのイベントループには何も伝わっていなかった。

実際に gateway のプロセスを起動して確かめる。見たいのは:

  1. SIGINT でも SIGTERM でも、stackd が SIGTERM に上げる前（5 秒）に終わる
  2. 終了コード 0。abort（-6）やスタックトレースを出さない
  3. **SIGINT が無視された状態で起動されても** SIGINT で止まる
     （シェルのバックグラウンドジョブは SIGINT が無視された状態で始まる）
"""

from __future__ import annotations

import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip('rclpy')
pytest.importorskip('aiohttp')

STARTUP_TIMEOUT_SEC = 30.0
STOP_BUDGET_SEC = 5.0
"""stackd は SIGINT から 5 秒で SIGTERM に上げる（supervisor.SIGINT_GRACE_SEC）。"""

READY = 'で待ち受け中'


def _free_port() -> int:
    # port の範囲は 1024 以上（params.yaml）なので 0 を渡せない。空いている番号を借りる。
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _start(ignore_sigint: bool) -> tuple[subprocess.Popen, queue.Queue]:
    env = {k: v for k, v in os.environ.items() if not k.startswith('WHILL_TLS')}
    env.update(
        WHILL_GATEWAY_TOKEN='signal-test-token',
        WHILL_TLS='off',
        # 走っている本物のスタックと DDS で混ざらないように
        ROS_DOMAIN_ID=str(150 + os.getpid() % 50),
        PYTHONUNBUFFERED='1',
    )

    def prepare() -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_DFL)
        if ignore_sigint:
            signal.signal(signal.SIGINT, signal.SIG_IGN)

    proc = subprocess.Popen(
        [sys.executable, '-m', 'whill_gateway.gateway', '--ros-args', '-p', f'port:={_free_port()}',
         '-p', 'bind_address:=127.0.0.1'],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        preexec_fn=prepare)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout],
                     daemon=True).start()
    return proc, lines


def _wait_ready(proc: subprocess.Popen, lines: queue.Queue) -> list[str]:
    seen: list[str] = []
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        seen.append(line)
        if READY in line:
            return seen
    proc.kill()
    pytest.fail('gateway が起動しなかった:\n' + ''.join(seen))


def _drain(lines: queue.Queue) -> str:
    out = []
    while True:
        try:
            out.append(lines.get(timeout=0.5))
        except queue.Empty:
            return ''.join(out)


@pytest.mark.parametrize('sig, ignore_sigint', [
    (signal.SIGINT, False),
    (signal.SIGTERM, False),
    (signal.SIGINT, True),
], ids=['SIGINT', 'SIGTERM', 'SIGINT-ignored-at-start'])
def test_gateway_stops_cleanly_on_signal(sig, ignore_sigint):
    proc, lines = _start(ignore_sigint)
    try:
        _wait_ready(proc, lines)
        started = time.monotonic()
        proc.send_signal(sig)
        try:
            code = proc.wait(timeout=STOP_BUDGET_SEC)
        except subprocess.TimeoutExpired:
            pytest.fail(f'{sig.name} から {STOP_BUDGET_SEC} 秒で止まらない')
        elapsed = time.monotonic() - started
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    output = _drain(lines)
    assert code == 0, f'終了コード {code}:\n{output}'
    assert elapsed < STOP_BUDGET_SEC
    assert f'{sig.name} を受けたので停止する' in output
    # abort やスタックトレースは「異常終了した」ように見え、本物の故障に紛れる
    assert 'Traceback' not in output, output
    assert 'terminate called' not in output, output


def test_second_signal_during_shutdown_is_quiet():
    """stackd のグループ宛て SIGINT と launch の転送で、ほぼ必ず 2 通来る。"""
    proc, lines = _start(ignore_sigint=False)
    try:
        _wait_ready(proc, lines)
        proc.send_signal(signal.SIGINT)
        proc.send_signal(signal.SIGINT)
        code = proc.wait(timeout=STOP_BUDGET_SEC)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    output = _drain(lines)
    assert code == 0, output
    assert 'Traceback' not in output, output
