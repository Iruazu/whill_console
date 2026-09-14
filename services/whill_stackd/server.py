"""stackd の WebSocket API。

実機PC に ssh せずに、他PC・tablet からスタックを起動・停止できるようにする。
gateway と同じ固定トークン認証で、同じ「最初のフレームで認証」の作法。

gateway と別プロセスなのは、**stackd が gateway を含むスタック全体を
起動・停止する側**だから。同じプロセスに入れると自分を殺すことになる。

## フレーム

    client → server : auth, start, stop, restart, status, logs
    server → client : hello, error, status, log, exited

`exited` は子プロセスが終わったときに流す。終了コードを添える。
**落ちたことを黙らない** ため、こちらから止めた場合も送る。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any

from whill_stackd.supervisor import LogLine, State, Supervisor, SupervisorError

LOGGER = logging.getLogger('whill_stackd')

PROTOCOL_VERSION = 1
AUTH_TIMEOUT_SEC = 5.0
DEFAULT_PORT = 8770

VALID_MODES = ('real', 'sim', 'replay', 'mock')


class StackdServer:
    def __init__(self, *, token: str, repo_root: str) -> None:
        if not token:
            raise ValueError('トークンが空。WHILL_GATEWAY_TOKEN を設定すること')
        self._token = token
        self.repo_root = repo_root
        self._clients: set[Any] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        # 送信タスクの参照を保持する。保持しないと GC に回収されて
        # 送信が途中で消えることがある（ログが歯抜けになる）。
        self._sends: set[asyncio.Task] = set()
        self.supervisor = Supervisor(on_log=self._on_log, on_state=self._on_state)

    # ---- 配信 --------------------------------------------------------------

    def _broadcast(self, frame: dict[str, Any]) -> None:
        payload = json.dumps(frame, ensure_ascii=False, separators=(',', ':'))
        for ws in list(self._clients):
            # 送信の完了は待たない。1 台の遅い端末でログの取り込みを
            # 止めないため。
            task = asyncio.ensure_future(self._send_safe(ws, payload))
            self._sends.add(task)
            task.add_done_callback(self._sends.discard)

    async def _send_safe(self, ws, payload: str) -> None:
        with contextlib.suppress(Exception):
            await ws.send(payload)

    def _on_log(self, line: LogLine) -> None:
        self._broadcast({'type': 'log', 'stream': line.stream,
                         'text': line.text, 'stamp': line.stamp})

    def _on_state(self, state: State) -> None:
        frame = {'type': 'status', **self.supervisor.status()}
        self._broadcast(frame)
        if state in (State.STOPPED, State.FAILED):
            # 終了コードを明示的に配る。status を読み落としても
            # 「終わった」ことだけは伝わるようにする。
            self._broadcast({
                'type': 'exited',
                'exit_code': self.supervisor.exit_code,
                'failed': state == State.FAILED,
            })

    # ---- 接続 --------------------------------------------------------------

    async def handle(self, ws, path: str | None = None) -> None:
        del path
        await ws.send(json.dumps({'type': 'hello', 'protocol': PROTOCOL_VERSION,
                                  'service': 'whill_stackd'}))
        try:
            raw = await asyncio.wait_for(ws.recv(), AUTH_TIMEOUT_SEC)
        except (asyncio.TimeoutError, Exception):
            return

        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await self._reject(ws, 'JSON として読めない')
            return

        token = message.get('token')
        if message.get('type') != 'auth' or not isinstance(token, str):
            await self._reject(ws, '最初のフレームは auth でなければならない')
            return
        import hmac
        if not hmac.compare_digest(token, self._token):
            await self._reject(ws, 'トークンが違う')
            return

        self._clients.add(ws)
        LOGGER.info('接続を受け付けた')
        try:
            await ws.send(json.dumps({'type': 'status',
                                      **self.supervisor.status()},
                                     ensure_ascii=False))
            await self._receive_loop(ws)
        # 切断は正常な終わり方。例外型で分岐しても扱いは同じ。
        except Exception:
            pass
        finally:
            self._clients.discard(ws)

    async def _reject(self, ws, reason: str) -> None:
        LOGGER.warning('拒否: %s', reason)
        with contextlib.suppress(Exception):
            await ws.send(json.dumps({'type': 'error', 'reason': reason,
                                      'fatal': True}, ensure_ascii=False))
        with contextlib.suppress(Exception):
            await ws.close()

    async def _receive_loop(self, ws) -> None:
        while True:
            raw = await ws.recv()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await self._send_safe(ws, json.dumps(
                    {'type': 'error', 'reason': 'JSON として読めない'},
                    ensure_ascii=False))
                continue
            await self._dispatch(ws, message)

    # ---- コマンド ----------------------------------------------------------

    async def _dispatch(self, ws, message: dict[str, Any]) -> None:
        kind = message.get('type')
        try:
            if kind == 'status':
                await self._send_safe(ws, json.dumps(
                    {'type': 'status', **self.supervisor.status()},
                    ensure_ascii=False))
            elif kind == 'logs':
                limit = message.get('limit', 100)
                for line in self.supervisor.recent_logs(int(limit)):
                    await self._send_safe(ws, json.dumps(
                        {'type': 'log', 'stream': line.stream,
                         'text': line.text, 'stamp': line.stamp},
                        ensure_ascii=False))
            elif kind == 'start':
                await self._start(message)
            elif kind == 'stop':
                await self.supervisor.stop()
            elif kind == 'restart':
                await self.supervisor.stop()
                await self._start(message)
            else:
                raise SupervisorError(f'未知の type: {kind}')
        except SupervisorError as exc:
            await self._send_safe(ws, json.dumps(
                {'type': 'error', 'reason': str(exc)}, ensure_ascii=False))

    async def _start(self, message: dict[str, Any]) -> None:
        robot = message.get('robot', 'cr2-01')
        mode = message.get('mode', 'mock')
        if not isinstance(robot, str) or not isinstance(mode, str):
            raise SupervisorError('robot / mode は文字列であること')
        if mode not in VALID_MODES:
            raise SupervisorError(f'未知のモード: {mode}')

        command = build_command(
            self.repo_root, robot=robot, mode=mode,
            preset=message.get('preset') or '',
            bag=message.get('bag') or '',
            camera=bool(message.get('camera')),
            gateway=bool(message.get('gateway', True)),
        )
        LOGGER.info('起動: %s', ' '.join(command))
        await self.supervisor.start(command, env=dict(os.environ))

    # ---- 待ち受け ----------------------------------------------------------

    async def serve(self, host: str, port: int, *, ssl_context=None):
        import websockets

        self._loop = asyncio.get_running_loop()
        server = await websockets.serve(self.handle, host, port, ssl=ssl_context)
        LOGGER.info('待ち受け開始: %s://%s:%d',
                    'wss' if ssl_context is not None else 'ws', host, port)
        if ssl_context is None:
            LOGGER.warning('TLS 未設定のため平文で待ち受ける。iPad から使うなら '
                           'WHILL_TLS_CERT / WHILL_TLS_KEY を設定すること')
        return server


def build_command(repo_root: str, *, robot: str, mode: str, preset: str = '',
                  bag: str = '', camera: bool = False,
                  gateway: bool = True) -> list[str]:
    """`whill run` を uv 経由で叩くコマンドを組む。

    `whill` を直接叩かず `uv run --project` を通すのは、stackd が systemd から
    起動されたときに PATH が薄いため。仮想環境の場所を明示する。
    """
    services = os.path.join(repo_root, 'services')
    command = [
        'uv', 'run', '--project', services, 'whill', 'run',
        '--robot', robot, '--mode', mode,
    ]
    if preset:
        command += ['--preset', preset]
    if bag:
        command += ['--bag', bag]
    if camera:
        command.append('--camera')
    if gateway:
        command.append('--gateway')
    return command
