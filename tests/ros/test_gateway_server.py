"""WebSocket サーバの挙動テスト。

本物の TCP は開かない。`GatewayServer` は websocket オブジェクトに対して
`recv` / `send` / `close` しか呼ばないので、その 3 つを持つ偽物を渡せば
認証とブロードキャストの筋は全部通せる。

見たいのは「認証を通さないと何も流れない」「遅いクライアントが全体を
止めない」の 2 点。どちらも実際に壊れると気づきにくい。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from whill_gateway import protocol
from whill_gateway.server import Client, GatewayServer

TOKEN = 'test-token-1234'


class FakeSocket:
    """recv / send / close だけを持つ偽の WebSocket。

    送るものが尽きたあとの振る舞いを 2 通り選べる:

      hold=False (既定) … `linger` 秒だけ開いたままにしてから切れる。
          サーバが返した応答フレームを送信ループが吐き出す時間を作るため。
          0 秒で切ると、キューに積まれた error フレームが観測できない。
      hold=True         … テストが release() を呼ぶまで開いたまま。
          broadcast の到達を確かめるテストで使う。
    """

    def __init__(self, incoming: list[str] | None = None,
                 remote: tuple[str, int] = ('192.168.1.50', 51234),
                 *, hold: bool = False, linger: float = 0.05) -> None:
        self._incoming = list(incoming or [])
        self.sent: list[str] = []
        self.closed = False
        self.remote_address = remote
        self._hold = hold
        self._linger = linger
        self._release = asyncio.Event()

    def release(self) -> None:
        self._release.set()

    async def recv(self) -> str:
        if self._incoming:
            return self._incoming.pop(0)
        if self._hold:
            await self._release.wait()
        else:
            await asyncio.sleep(self._linger)
        raise ConnectionResetError('fake closed')

    async def send(self, payload: str) -> None:
        if self.closed:
            raise ConnectionResetError('fake closed')
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def frames(self) -> list[dict]:
        return [json.loads(p) for p in self.sent]

    def kinds(self) -> list[str]:
        return [f['type'] for f in self.frames()]


class StuckSocket(FakeSocket):
    """接続はできるが、その後の送信が返らなくなるクライアントの模擬。

    最初の `allow` 通（hello と認証後の hello）は普通に受け取る。ここまで
    止めてしまうと認証が終わらず、「認証済みの遅いクライアント」という
    見たい状況にならない。実際の遅い端末も、繋がった後に詰まる。
    """

    def __init__(self, *args, allow: int = 2, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._allow = allow

    async def send(self, payload: str) -> None:
        if len(self.sent) < self._allow:
            await super().send(payload)
            return
        await asyncio.Event().wait()


def auth(token: str = TOKEN) -> str:
    return json.dumps({'type': 'auth', 'token': token})


def make_server(**kwargs) -> GatewayServer:
    return GatewayServer(token=TOKEN, robot_id='cr2-01', mode='mock', **kwargs)


# ---- 起動時の門番 ----------------------------------------------------------


def test_empty_token_is_refused_at_construction():
    """無認証で待ち受ける状態を作らせない。"""
    with pytest.raises(ValueError, match='トークンが空'):
        GatewayServer(token='', robot_id='cr2-01', mode='mock')


# ---- 認証 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hello_is_sent_before_auth():
    """繋いだ直後に hello が返る。認証前でもここまでは見せる。"""
    socket = FakeSocket([])
    await make_server().handle(socket)
    assert socket.kinds()[0] == protocol.MSG_HELLO
    assert socket.frames()[0]['authenticated'] is False


@pytest.mark.asyncio
async def test_correct_token_authenticates():
    socket = FakeSocket([auth()])
    await make_server().handle(socket)
    hellos = [f for f in socket.frames() if f['type'] == protocol.MSG_HELLO]
    assert hellos[-1]['authenticated'] is True


@pytest.mark.asyncio
async def test_wrong_token_is_rejected_with_a_reason():
    """黙って切らない。理由が無いと切り分けができない。"""
    socket = FakeSocket([auth('wrong')])
    await make_server().handle(socket)
    errors = [f for f in socket.frames() if f['type'] == protocol.MSG_ERROR]
    assert errors and 'トークン' in errors[-1]['reason']
    assert errors[-1]['fatal'] is True
    assert socket.closed


@pytest.mark.asyncio
async def test_non_string_token_is_rejected_without_crashing():
    """None や dict を投げられても例外にしない。"""
    socket = FakeSocket([json.dumps({'type': 'auth', 'token': None})])
    await make_server().handle(socket)
    assert socket.closed


@pytest.mark.asyncio
async def test_first_frame_must_be_auth():
    socket = FakeSocket([json.dumps({'type': 'heartbeat'})])
    await make_server().handle(socket)
    errors = [f for f in socket.frames() if f['type'] == protocol.MSG_ERROR]
    assert errors and 'auth' in errors[-1]['reason']


@pytest.mark.asyncio
async def test_broken_first_frame_is_rejected():
    socket = FakeSocket(['{{{'])
    await make_server().handle(socket)
    errors = [f for f in socket.frames() if f['type'] == protocol.MSG_ERROR]
    assert errors and 'JSON' in errors[-1]['reason']


@pytest.mark.asyncio
async def test_unauthenticated_client_receives_no_data():
    """認証前のクライアントにテレメトリを配らない。"""
    server = make_server()
    socket = FakeSocket([])
    task = asyncio.ensure_future(server.handle(socket))
    await asyncio.sleep(0)

    server.broadcast({'type': protocol.MSG_COSTMAP, 'rle': [0, 4]})
    server.broadcast({'type': protocol.MSG_STATUS, 'estop': False})
    await task

    assert protocol.MSG_COSTMAP not in socket.kinds()
    assert protocol.MSG_STATUS not in socket.kinds()


# ---- ブロードキャスト ------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_reaches_authenticated_client():
    server = make_server()
    socket = FakeSocket([auth()], hold=True)
    task = asyncio.ensure_future(server.handle(socket))
    await asyncio.sleep(0.01)

    assert server.clients == 1
    assert server.broadcast({'type': protocol.MSG_COSTMAP, 'rle': [0, 4]}) == 1
    await asyncio.sleep(0.01)
    assert protocol.MSG_COSTMAP in socket.kinds()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_broadcast_respects_subscription():
    """購読していないストリームは届かない。"""
    server = make_server()
    subscribe = json.dumps({'type': 'subscribe', 'streams': [protocol.MSG_POSE]})
    socket = FakeSocket([auth(), subscribe], hold=True)
    task = asyncio.ensure_future(server.handle(socket))
    await asyncio.sleep(0.01)

    server.broadcast({'type': protocol.MSG_COSTMAP, 'rle': [0, 4]})
    server.broadcast({'type': protocol.MSG_POSE, 'x': 1.0})
    await asyncio.sleep(0.01)

    assert protocol.MSG_COSTMAP not in socket.kinds()
    assert protocol.MSG_POSE in socket.kinds()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_status_ignores_subscription():
    """E-stop の状態が一部のクライアントにだけ届かない、を避ける。"""
    server = make_server()
    subscribe = json.dumps({'type': 'subscribe', 'streams': [protocol.MSG_POSE]})
    socket = FakeSocket([auth(), subscribe], hold=True)
    task = asyncio.ensure_future(server.handle(socket))
    await asyncio.sleep(0.01)

    server.broadcast({'type': protocol.MSG_STATUS, 'estop': True})
    await asyncio.sleep(0.01)
    assert protocol.MSG_STATUS in socket.kinds()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_slow_client_does_not_block_others():
    """遅い tablet が 1 台居るだけで全体の配信が止まらないこと。"""
    server = make_server()
    slow = StuckSocket([auth()], hold=True)
    fast = FakeSocket([auth()], hold=True)
    slow_task = asyncio.ensure_future(server.handle(slow))
    fast_task = asyncio.ensure_future(server.handle(fast))
    await asyncio.sleep(0.01)

    # 実際の配信は ROS のコールバック由来で、フレームの合間に必ず制御が
    # 戻る。ここでも 1 通ごとに yield する。yield せずに詰め込むと健全な
    # クライアントのキューまで溢れ、「遅いクライアントだけが切られる」
    # ことを確かめられない。
    for i in range(100):
        server.broadcast({'type': protocol.MSG_COSTMAP, 'seq': i})
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)

    fast_costmaps = len([k for k in fast.kinds() if k == protocol.MSG_COSTMAP])
    assert fast_costmaps > 90, f'健全なクライアントが取りこぼしている ({fast_costmaps})'
    # 印を付けるだけでは不十分。繋がったまま黙って捨て続ける状態にしない。
    assert slow.closed, '遅いクライアントが切断されていない'

    for task in (slow_task, fast_task):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---- 受信ループ ------------------------------------------------------------


@pytest.mark.asyncio
async def test_broken_frame_does_not_close_the_connection():
    """UI のバグ 1 個で再接続ループに陥らせない。"""
    handled: list[str] = []

    async def on_message(client: Client, message: dict) -> None:
        handled.append(message['type'])

    server = make_server(on_message=on_message)
    socket = FakeSocket([auth(), '{{{', json.dumps({'type': 'heartbeat'})])
    await server.handle(socket)

    assert handled == ['heartbeat'], '壊れたフレームの後も処理が続くこと'
    errors = [f for f in socket.frames() if f['type'] == protocol.MSG_ERROR]
    assert errors and not errors[-1]['fatal']


@pytest.mark.asyncio
async def test_handler_protocol_error_becomes_an_error_frame():
    async def on_message(client: Client, message: dict) -> None:
        raise protocol.ProtocolError('値が範囲外')

    server = make_server(on_message=on_message)
    socket = FakeSocket([auth(), json.dumps({'type': 'heartbeat'})])
    await server.handle(socket)

    errors = [f for f in socket.frames() if f['type'] == protocol.MSG_ERROR]
    assert errors and errors[-1]['reason'] == '値が範囲外'


@pytest.mark.asyncio
async def test_connect_and_disconnect_hooks_fire():
    events: list[str] = []

    async def on_connect(client: Client) -> None:
        events.append('connect')

    async def on_disconnect(client: Client) -> None:
        events.append('disconnect')

    server = make_server(on_connect=on_connect, on_disconnect=on_disconnect)
    await server.handle(FakeSocket([auth()]))
    assert events == ['connect', 'disconnect']


@pytest.mark.asyncio
async def test_disconnect_hook_does_not_fire_for_unauthenticated():
    """認証していない接続は「繋がった」ことにしない。"""
    events: list[str] = []

    async def on_disconnect(client: Client) -> None:
        events.append('disconnect')

    server = make_server(on_disconnect=on_disconnect)
    await server.handle(FakeSocket([auth('wrong')]))
    assert events == []


# ---- 認証待ちの打ち切り ----------------------------------------------------


@pytest.mark.asyncio
async def test_auth_timeout_closes_the_connection(monkeypatch):
    """認証フレームを送ってこない接続を開いたまま放置しない。"""
    import whill_gateway.server as server_module
    monkeypatch.setattr(server_module, 'AUTH_TIMEOUT_SEC', 0.01)

    class SilentSocket(FakeSocket):
        async def recv(self):
            await asyncio.Event().wait()

    socket = SilentSocket()
    await make_server().handle(socket)
    assert socket.closed
    errors = [f for f in socket.frames() if f['type'] == protocol.MSG_ERROR]
    assert errors and '認証フレーム' in errors[-1]['reason']


# ---- 購読の帰属と再配布 ----------------------------------------------------


@pytest.mark.asyncio
async def test_costmap_update_follows_the_costmap_subscription():
    """costmap を購読していれば部分更新も届くこと。

    届かないと地図が最初の 1 枚で固まる（ADR-0002）。実機で気づくと
    「なぜか画面が更新されない」という切り分けにくい症状になる。
    """
    server = make_server()
    subscribe = json.dumps({'type': 'subscribe', 'streams': [protocol.MSG_COSTMAP]})
    socket = FakeSocket([auth(), subscribe], hold=True)
    task = asyncio.ensure_future(server.handle(socket))
    await asyncio.sleep(0.01)

    server.broadcast({'type': protocol.MSG_COSTMAP_UPDATE, 'x': 0, 'y': 0})
    await asyncio.sleep(0.01)
    assert protocol.MSG_COSTMAP_UPDATE in socket.kinds()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_subscribe_triggers_a_resend_of_current_state():
    """購読を変えたら、いま持っている状態を配り直すこと。

    後から costmap を購読したクライアントは、これが無いと「次の publish」を
    永久に待つ。Nav2 は全量を二度と出さない（ADR-0002）。
    """
    sent_snapshots = 0

    async def on_subscribe(client: Client) -> None:
        nonlocal sent_snapshots
        sent_snapshots += 1
        client.enqueue(protocol.safe_encode({'type': protocol.MSG_COSTMAP, 'rle': [0, 1]}))

    server = make_server(on_subscribe=on_subscribe)
    subscribe = json.dumps({'type': 'subscribe', 'streams': [protocol.MSG_COSTMAP]})
    socket = FakeSocket([auth(), subscribe], hold=True)
    task = asyncio.ensure_future(server.handle(socket))
    await asyncio.sleep(0.02)

    assert sent_snapshots == 1
    assert protocol.MSG_COSTMAP in socket.kinds()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_bad_subscribe_does_not_trigger_a_resend():
    """不正な購読要求では配り直さない（拒否したのに状態を送るのは矛盾）。"""
    called = False

    async def on_subscribe(client: Client) -> None:
        nonlocal called
        called = True

    server = make_server(on_subscribe=on_subscribe)
    bad = json.dumps({'type': 'subscribe', 'streams': ['costmpa']})
    socket = FakeSocket([auth(), bad])
    await server.handle(socket)

    assert called is False
    errors = [f for f in socket.frames() if f['type'] == protocol.MSG_ERROR]
    assert errors and '未知のストリーム' in errors[-1]['reason']
