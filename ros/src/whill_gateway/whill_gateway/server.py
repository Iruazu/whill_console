"""WebSocket サーバ本体。ROS からは切り離してある。

`GatewayServer` は ROS を知らない。知っているのは「認証」「接続の管理」
「ブロードキャスト」だけ。ROS 側との受け渡しは `handlers` 経由の呼び出しと
`broadcast()` の呼び出しで行う。

こうしてあるのは、ROS を立てずにサーバの挙動（認証を通さないと何も流れない、
遅いクライアントが全体を止めない）をテストするため。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from whill_gateway import protocol

LOGGER = logging.getLogger('whill_gateway.server')

AUTH_TIMEOUT_SEC = 5.0
"""接続してから認証フレームを送ってくるまでの猶予。

無認証の接続を開いたまま放置させないための上限。短すぎると遅い回線で
繋がらないので、Wi-Fi 越しの実測を見て調整する（実機検証待ち）。
"""

SEND_QUEUE_LIMIT = 32
"""1 クライアントあたりの送信キュー長。

これを超えたクライアントは切る。遅い端末（tablet）が 1 台居るだけで
全体の配信が止まるのを避けるため。切られた側は再接続すればよい。
"""


class Client:
    """接続 1 本ぶんの状態。"""

    def __init__(self, websocket: Any, remote: str) -> None:
        self.websocket = websocket
        self.remote = remote
        self.authenticated = False
        self.streams: frozenset[str] = frozenset()
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SEND_QUEUE_LIMIT)
        self.dropped = False
        self.drop_scheduled = False

    def wants(self, kind: str) -> bool:
        return kind in self.streams

    def enqueue(self, payload: str) -> bool:
        """送信キューに積む。詰まっていたら False。"""
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.dropped = True
            return False
        return True


MessageHandler = Callable[[Client, dict[str, Any]], Awaitable[None]]


class GatewayServer:
    """認証つきの WebSocket ブロードキャストサーバ。

    ROS 依存はここには無い。`on_message` に渡されたハンドラが ROS を触る。
    """

    def __init__(self, *, token: str, robot_id: str, mode: str,
                 on_message: MessageHandler | None = None,
                 on_connect: Callable[[Client], Awaitable[None]] | None = None,
                 on_disconnect: Callable[[Client], Awaitable[None]] | None = None) -> None:
        if not token:
            # 起動前に必ず落とす。無認証で待ち受ける状態を作らない。
            raise ValueError('トークンが空。WHILL_GATEWAY_TOKEN を設定すること')
        self._token = token
        self.robot_id = robot_id
        self.mode = mode
        self._on_message = on_message
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._clients: set[Client] = set()
        self._server: Any = None

    # ---- 接続の管理 --------------------------------------------------------

    @property
    def clients(self) -> int:
        return sum(1 for c in self._clients if c.authenticated)

    async def handle(self, websocket: Any, path: str | None = None) -> None:
        """1 接続ぶんのライフサイクル。

        websockets 9.x はハンドラに (websocket, path) を渡し、12.x 以降は
        (websocket) だけを渡す。どちらでも動くよう path を省略可にしている。
        """
        del path  # 経路でルーティングしない。1 エンドポイントのみ
        remote = _remote_of(websocket)
        client = Client(websocket, remote)
        self._clients.add(client)
        LOGGER.info('接続: %s', remote)

        sender = asyncio.ensure_future(self._sender_loop(client))
        try:
            await self._send_now(client, protocol.hello(
                robot_id=self.robot_id, mode=self.mode, authenticated=False))
            if not await self._await_auth(client):
                return
            if self._on_connect:
                await self._on_connect(client)
            await self._receive_loop(client)
        except _ConnectionClosed:
            LOGGER.info('切断: %s', remote)
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
            self._clients.discard(client)
            if client.authenticated and self._on_disconnect:
                await self._on_disconnect(client)

    async def _await_auth(self, client: Client) -> bool:
        """最初のフレームで認証する。通らなければ理由を返してから切る。"""
        try:
            raw = await asyncio.wait_for(client.websocket.recv(), AUTH_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            await self._reject(client, '認証フレームが来ない')
            return False
        except Exception as exc:  # noqa: BLE001 - websockets の例外型に依存しない
            raise _ConnectionClosed from exc

        try:
            message = protocol.parse_client_message(raw)
        except protocol.ProtocolError as exc:
            await self._reject(client, str(exc))
            return False

        if message.get('type') != protocol.MSG_AUTH:
            await self._reject(client, '最初のフレームは auth でなければならない')
            return False

        token = message.get('token')
        # 比較の前に型を見る。None や dict を渡されて例外にしない。
        if not isinstance(token, str) or not _constant_time_equals(token, self._token):
            await self._reject(client, 'トークンが違う')
            return False

        client.authenticated = True
        client.streams = frozenset(protocol.DEFAULT_STREAMS)
        await self._send_now(client, protocol.hello(
            robot_id=self.robot_id, mode=self.mode, authenticated=True))
        LOGGER.info('認証成功: %s', client.remote)
        return True

    async def _reject(self, client: Client, reason: str) -> None:
        LOGGER.warning('認証拒否 %s: %s', client.remote, reason)
        with contextlib.suppress(Exception):
            await self._send_now(client, protocol.error(reason, fatal=True))
        with contextlib.suppress(Exception):
            await client.websocket.close()

    async def _receive_loop(self, client: Client) -> None:
        while True:
            try:
                raw = await client.websocket.recv()
            except Exception as exc:  # noqa: BLE001
                raise _ConnectionClosed from exc

            try:
                message = protocol.parse_client_message(raw)
            except protocol.ProtocolError as exc:
                # 壊れたフレーム 1 通で接続を切らない。UI のバグで
                # 再接続ループに陥ると、かえって切り分けが難しくなる。
                await self._send(client, protocol.error(str(exc)))
                continue

            if message['type'] == protocol.MSG_SUBSCRIBE:
                try:
                    client.streams = protocol.parse_subscribe(message)
                except protocol.ProtocolError as exc:
                    await self._send(client, protocol.error(str(exc)))
                continue

            if self._on_message:
                try:
                    await self._on_message(client, message)
                except protocol.ProtocolError as exc:
                    await self._send(client, protocol.error(str(exc)))

    # ---- 送信 --------------------------------------------------------------

    async def _sender_loop(self, client: Client) -> None:
        """キューから取り出して送るだけのループ。

        送信を受信ループから分離しているのは、遅いクライアントへの送信待ちで
        そのクライアントの受信（E-stop を含む）が止まらないようにするため。
        """
        while True:
            payload = await client.queue.get()
            try:
                await client.websocket.send(payload)
            except Exception:  # noqa: BLE001
                return

    async def _send_now(self, client: Client, message: dict[str, Any]) -> None:
        """キューを通さず直に送る。hello と拒否理由だけに使う。"""
        try:
            await client.websocket.send(protocol.safe_encode(message))
        except Exception as exc:  # noqa: BLE001
            raise _ConnectionClosed from exc

    async def _send(self, client: Client, message: dict[str, Any]) -> None:
        if not client.enqueue(protocol.safe_encode(message)):
            LOGGER.warning('送信キューが詰まったので切断: %s', client.remote)
            with contextlib.suppress(Exception):
                await client.websocket.close()

    def broadcast(self, message: dict[str, Any]) -> int:
        """認証済みかつそのストリームを購読しているクライアントに配る。

        同期関数。ROS 側のコールバックから `loop.call_soon_threadsafe` 経由で
        呼ばれるため、await しない。キューが詰まったクライアントは切断を
        予約する（実際の close は別タスク）。**印を付けるだけにしない**こと。
        印だけだと、詰まった端末が繋がったまま黙ってフレームを捨て続け、
        「繋がっているのに画面が更新されない」という一番切り分けにくい
        状態になる。
        """
        kind = message.get('type', '')
        payload = protocol.safe_encode(message)
        sent = 0
        for client in list(self._clients):
            if not client.authenticated:
                continue
            # status と error は購読指定に関係なく配る。E-stop の状態が
            # 一部のクライアントにだけ届かない、という事態を避ける。
            if kind not in (protocol.MSG_STATUS, protocol.MSG_ERROR) \
                    and not client.wants(kind):
                continue
            if client.enqueue(payload):
                sent += 1
            else:
                self._schedule_drop(client)
        return sent

    def _schedule_drop(self, client: Client) -> None:
        """送信が追いつかないクライアントを切る。再接続はクライアントの責任。"""
        if client.drop_scheduled:
            return
        client.drop_scheduled = True
        LOGGER.warning('送信キューが詰まったので切断する: %s', client.remote)
        asyncio.ensure_future(self._close_client(client))

    async def _close_client(self, client: Client) -> None:
        with contextlib.suppress(Exception):
            await client.websocket.close()

    # ---- 起動 --------------------------------------------------------------

    async def serve(self, host: str, port: int) -> Any:
        """aiohttp で待ち受ける。

        websockets ライブラリを使っていない理由は ADR-0003 を参照。要約すると、
        Ubuntu 22.04 の apt で入る python3-websockets は 9.1 で、Python 3.10 で
        壊れている（`asyncio.Lock(loop=...)` が 3.10 で削除された引数を渡す）。
        サーバ側も接続時に必ず落ちる。pip で新しい版を混ぜると ROS の
        python 環境が apt と食い違うため、apt で入る aiohttp にした。

        `handle()` は aiohttp を知らない。`_AiohttpSocket` が recv/send/close の
        3 つに揃えて渡す。テストの偽ソケットと同じ形。
        """
        from aiohttp import web

        async def _handler(request):
            ws = web.WebSocketResponse(
                # 既定の 4 MiB では全域 costmap が入らないことがある
                max_msg_size=8 * 1024 * 1024,
                # ping で切断を検出する。tablet がスリープしたまま
                # 接続だけ残るのを防ぐ。
                heartbeat=20.0,
                compress=True,
            )
            await ws.prepare(request)
            await self.handle(_AiohttpSocket(ws, request))
            return ws

        app = web.Application()
        app.router.add_get('/', _handler)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        self._server = runner
        LOGGER.info('待ち受け開始: ws://%s:%d', host, port)
        return runner

    async def close(self) -> None:
        for client in list(self._clients):
            with contextlib.suppress(Exception):
                await client.websocket.close()
        if self._server is not None:
            await self._server.cleanup()


class _AiohttpSocket:
    """aiohttp の WebSocketResponse を recv/send/close の 3 つに揃える。

    `GatewayServer` を特定のライブラリに縛らないための薄い層。テストでは
    同じ 3 メソッドを持つ偽物を渡す。
    """

    def __init__(self, ws: Any, request: Any) -> None:
        self._ws = ws
        peer = request.transport.get_extra_info('peername') if request.transport else None
        self.remote_address = peer

    async def recv(self) -> str:
        from aiohttp import WSMsgType

        message = await self._ws.receive()
        if message.type == WSMsgType.TEXT:
            return message.data
        if message.type == WSMsgType.BINARY:
            # 受信は JSON テキストのみ。binary は上り方向では使わない。
            raise ConnectionResetError('binary フレームは受け付けない')
        # CLOSE / CLOSING / CLOSED / ERROR
        raise ConnectionResetError(f'接続が閉じた: {message.type}')

    async def send(self, payload: str) -> None:
        await self._ws.send_str(payload)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()


class _ConnectionClosed(Exception):
    """websockets の例外型に直接依存しないための内部例外。"""


def _remote_of(websocket: Any) -> str:
    remote = getattr(websocket, 'remote_address', None)
    if isinstance(remote, tuple) and remote:
        return f'{remote[0]}:{remote[1]}' if len(remote) > 1 else str(remote[0])
    return str(remote)


def _constant_time_equals(a: str, b: str) -> bool:
    """比較時間でトークンを推測されないようにする。

    LAN 限定でこの攻撃が現実的かは怪しいが、標準ライブラリで済むので使う。
    """
    import hmac
    return hmac.compare_digest(a, b)
