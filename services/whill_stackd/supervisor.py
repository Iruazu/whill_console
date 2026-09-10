"""`whill run` を子プロセスとして管理する。

このモジュールは WebSocket も ROS も知らない。知っているのは「プロセスを
起動して、出力を行単位で拾い、確実に止める」ことだけ。おかげで ROS を
立てずにテストできる（CI の services ジョブで回る）。

## 止め方

`pkill -INT` に頼らない。`ros2 launch` の子プロセスには SIGINT が確実には
伝播せず、孤児になった `static_transform_publisher` や driver が生き残って
次の起動と喧嘩する（既存リポで実証済み）。

代わりに **新しいプロセスグループで起動し、グループごと落とす**。
SIGINT → 猶予 → SIGTERM → 猶予 → SIGKILL の順で、段階的に強くする。
いきなり SIGKILL にしないのは、ROS ノードに終了処理（bag の flush 等）を
させるため。

## 終了コード

**落ちたことを黙らない。** 正常終了・異常終了・こちらから止めた、を
区別して配信する。「止まっているように見えるが理由が分からない」状態を
作らないため。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

SIGINT_GRACE_SEC = 5.0
"""SIGINT を送ってから SIGTERM に上げるまで。

Nav2 の lifecycle 停止と bag の flush が終わる程度は待つ。
"""

SIGTERM_GRACE_SEC = 3.0
"""SIGTERM を送ってから SIGKILL に上げるまで。"""

LOG_BUFFER_LINES = 500
"""保持するログ行数。

後から繋いだクライアントに直近を見せるため。全部持つとメモリを食うし、
古すぎる行は役に立たない。
"""


class State(str, Enum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    FAILED = 'failed'
    """異常終了した。終了コードを添えて配信する。"""


@dataclass
class LogLine:
    stream: str
    """'stdout' または 'stderr'。"""
    text: str
    stamp: float


class SupervisorError(Exception):
    """要求が現在の状態では実行できない。"""


class Supervisor:
    """子プロセスを 1 つだけ管理する。

    2 つ同時に走らせない。同じ個体に対して 2 セット起動すると、ノードが
    二重になって `/velodyne_points` が倍のレートで流れる（既存リポで実証済み）。
    """

    def __init__(self, *, on_log: Callable[[LogLine], None] | None = None,
                 on_state: Callable[[State], None] | None = None) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._state = State.STOPPED
        self._logs: deque[LogLine] = deque(maxlen=LOG_BUFFER_LINES)
        self._on_log = on_log
        self._on_state = on_state
        self._exit_code: int | None = None
        self._stopping_on_purpose = False
        self._command: list[str] = []
        self._started_at: float | None = None
        self._pumps: list[asyncio.Task] = []
        self._waiter: asyncio.Task | None = None
        self._pgid: int | None = None
        """起動時に控えるプロセスグループ ID。

        親が終了すると `os.getpgid(pid)` は引けなくなる。孫が残っているかを
        親の死後にも確かめる必要があるので、最初に控えておく。
        """

    # ---- 参照 --------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def command(self) -> list[str]:
        return list(self._command)

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def recent_logs(self, limit: int | None = None) -> list[LogLine]:
        lines = list(self._logs)
        return lines[-limit:] if limit else lines

    def status(self) -> dict:
        return {
            'state': self._state.value,
            'pid': self.pid,
            'command': self.command,
            'exit_code': self._exit_code,
            'uptime': (time.time() - self._started_at) if self._started_at else None,
        }

    # ---- 起動 --------------------------------------------------------------

    async def start(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        if self._state in (State.STARTING, State.RUNNING, State.STOPPING):
            raise SupervisorError(f'既に {self._state.value} なので起動できない')

        self._command = list(command)
        self._exit_code = None
        self._stopping_on_purpose = False
        self._set_state(State.STARTING)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                # 新しいセッション = 新しいプロセスグループ。これがあるから
                # グループごと確実に落とせる。
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            self._set_state(State.FAILED)
            self._exit_code = 127
            raise SupervisorError(f'起動できない: {exc}') from exc

        self._started_at = time.time()
        try:
            self._pgid = os.getpgid(self._process.pid)
        except (ProcessLookupError, PermissionError):
            self._pgid = None
        self._pumps = [
            asyncio.ensure_future(self._pump(self._process.stdout, 'stdout')),
            asyncio.ensure_future(self._pump(self._process.stderr, 'stderr')),
        ]
        self._waiter = asyncio.ensure_future(self._wait_for_exit())
        self._set_state(State.RUNNING)

    async def _pump(self, stream, name: str) -> None:
        """出力を行単位で拾う。

        まとめてではなく行ごとに流すのは、UI のログ tail を「起動中に
        いま何が起きているか」が見えるものにするため。
        """
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                return
            line = LogLine(
                stream=name,
                text=raw.decode('utf-8', errors='replace').rstrip('\n'),
                stamp=time.time(),
            )
            self._logs.append(line)
            if self._on_log:
                self._on_log(line)

    async def _wait_for_exit(self) -> None:
        assert self._process is not None
        code = await self._process.wait()
        # 出力を取りこぼさないよう、pump が終わるのを待つ
        for pump in self._pumps:
            with contextlib.suppress(asyncio.CancelledError):
                await pump
        self._exit_code = code
        self._started_at = None

        if self._stopping_on_purpose:
            self._set_state(State.STOPPED)
        elif code == 0:
            self._set_state(State.STOPPED)
        else:
            # 落ちたことを黙らない。
            self._set_state(State.FAILED)

    # ---- 停止 --------------------------------------------------------------

    async def stop(self) -> int | None:
        """プロセスグループごと止める。終了コードを返す。

        既に止まっていれば何もしない（冪等）。

        **親が終了しただけで「止まった」と返さない。** `ros2 launch` の子は
        SIGINT を取りこぼすことがあり、親だけ落ちて driver や
        static_transform_publisher が孤児として生き残る（既存リポで実証済み）。
        グループが空になるまで段階を上げ続ける。
        """
        if self._process is None or self._state in (State.STOPPED, State.FAILED):
            return self._exit_code

        self._stopping_on_purpose = True
        self._set_state(State.STOPPING)

        for sig, grace in ((signal.SIGINT, SIGINT_GRACE_SEC),
                           (signal.SIGTERM, SIGTERM_GRACE_SEC)):
            if not self._signal_group(sig):
                break
            if await self._wait_for_group_exit(grace):
                return self._exit_code

        # ここまで来たら容赦しない。孤児が残ると次の起動と喧嘩する。
        self._signal_group(signal.SIGKILL)
        await self._wait_for_group_exit(3.0)
        return self._exit_code

    async def _wait_for_group_exit(self, timeout: float) -> bool:
        """親の終了とグループの消滅の両方を待つ。

        親だけ見ると、孫が生き残っているのに「停止した」と報告してしまう。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        if self._waiter is not None:
            remaining = deadline - loop.time()
            if remaining > 0:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(self._waiter), remaining)

        while loop.time() < deadline:
            if not self._group_alive():
                return True
            await asyncio.sleep(0.1)
        return not self._group_alive()

    def _group_alive(self) -> bool:
        """プロセスグループにまだ誰か居るか。

        シグナル 0 は「送れるか確かめるだけ」。グループに 1 つでも生きた
        プロセスがあれば成功する。
        """
        if self._pgid is None:
            return self._process is not None and self._process.returncode is None
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _signal_group(self, sig: signal.Signals) -> bool:
        """プロセスグループ全体にシグナルを送る。送れたら True。

        `process.send_signal` は親 1 つにしか届かない。`ros2 launch` の
        子（driver、static_transform_publisher 等）を確実に落とすには
        グループへ送る必要がある。
        """
        if self._process is None:
            return False
        # 親が終了していてもグループに孫が残っていることがあるので、
        # returncode では判定しない。控えた pgid へ送る。
        if self._pgid is None and self._process.returncode is not None:
            return False
        try:
            os.killpg(self._pgid if self._pgid is not None
                      else os.getpgid(self._process.pid), sig)
        except ProcessLookupError:
            return False
        except PermissionError:
            # グループが作れていない環境。せめて親には送る。
            with contextlib.suppress(ProcessLookupError):
                self._process.send_signal(sig)
        return True

    async def restart(self, command: list[str], *,
                      env: dict[str, str] | None = None) -> None:
        await self.stop()
        await self.start(command, env=env)

    # ---- 内部 --------------------------------------------------------------

    def _set_state(self, state: State) -> None:
        if state == self._state:
            return
        self._state = state
        if self._on_state:
            self._on_state(state)
