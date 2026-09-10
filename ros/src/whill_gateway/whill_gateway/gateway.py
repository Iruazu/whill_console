"""whill_gateway — ROS と Web の唯一の接点。

設計原則 1: 外部との接続はこの WebSocket 1 本と ssh のみ。多マシン DDS は
組まない。したがってこのノードが落ちると外から何も見えなくなるので、
「落ちにくいこと」より「落ちたと分かること」を優先する。

## スレッド構成

    メインスレッド : asyncio のイベントループ（WebSocket サーバ）
    別スレッド     : rclpy の executor（ROS コールバック）

ROS コールバック → asyncio へは `loop.call_soon_threadsafe` で渡す。逆向き
（Web からの指令 → ROS）は、asyncio 側から rclpy の publisher / client を
直接呼ぶ。rclpy の publish はスレッドセーフ。

**安全に関わる処理（ハートビート監視）は ROS のタイマー側に置くこと。**
asyncio 側に置くと、WebSocket の処理が詰まったときに一緒に止まる
（設計原則 4 に反する）。実装は #12。

この issue (#9) の範囲は骨格まで。テレメトリ配信は #10、param は #11、
手動操作と E-stop は #12。
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node

from whill_gateway import protocol
from whill_gateway.server import Client, GatewayServer
from whill_gateway.telemetry import Telemetry
from whill_params import registry as reg
from whill_params.descriptors import declare_from_registry

STATUS_PERIOD_SEC = 1.0
"""`status` フレームの配信周期。上部帯の更新なので 1 Hz で足りる。"""

TF_SUMMARY_PERIOD_SEC = 2.0
"""tf 要約の配信周期。中身が変わったときだけ実際に流れる。"""


class Gateway(Node):

    def __init__(self) -> None:
        super().__init__('whill_gateway')

        self.declare_parameter('robot_id', 'cr2-01')
        self.declare_parameter('mode', 'mock')
        self.robot_id = self.get_parameter('robot_id').value
        self.mode = self.get_parameter('mode').value

        self.registry = reg.load(self.robot_id)
        declared = declare_from_registry(self, self.registry, node_name='whill_gateway')
        self.get_logger().info(f'registry から {len(declared)} 個のパラメータを宣言した')

        self.bind_address = self.get_parameter('bind_address').value
        self.port = int(self.get_parameter('port').value)

        # asyncio 側からセットされる。ROS コールバックはこれ経由で送る。
        self._loop: asyncio.AbstractEventLoop | None = None
        self.server: GatewayServer | None = None

        # #12 で埋める。ここでは status に載せるためだけに持つ。
        self.estop = False
        self.nav_active = False

        self.telemetry = Telemetry(
            self, self.emit,
            costmap_hz=float(self.get_parameter('costmap_publish_rate').value),
            pose_hz=float(self.get_parameter('pose_publish_rate').value),
            image_hz=float(self.get_parameter('image_publish_rate').value),
        )
        # live パラメータなので、走行中に変えられる。set のたびに反映する。
        self.add_on_set_parameters_callback(self._on_parameters_set)

        self.create_timer(STATUS_PERIOD_SEC, self._publish_status)
        self.create_timer(TF_SUMMARY_PERIOD_SEC, self.telemetry.publish_tf_summary)

    # ---- ROS → Web ---------------------------------------------------------

    def emit(self, message: dict[str, Any]) -> None:
        """ROS のスレッドから Web へ配る。

        asyncio のループがまだ無い/既に閉じている場合は黙って捨てる。
        起動直後と終了処理中に呼ばれうるため。
        """
        loop, server = self._loop, self.server
        if loop is None or server is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(server.broadcast, message)

    def _on_parameters_set(self, params):
        """live なレート指定を Telemetry に伝える。

        `SetParametersResult(successful=True)` を返さないと ros2 param set が
        失敗する。値の妥当性は registry 側（ParameterDescriptor の範囲）が見る。
        """
        from rcl_interfaces.msg import SetParametersResult

        names = ('costmap_publish_rate', 'pose_publish_rate', 'image_publish_rate')
        incoming = {p.name: float(p.value) for p in params if p.name in names}
        if incoming:
            resolved = {
                name: incoming.get(name, float(self.get_parameter(name).value))
                for name in names
            }
            self.telemetry.set_rates(
                costmap_hz=resolved['costmap_publish_rate'],
                pose_hz=resolved['pose_publish_rate'],
                image_hz=resolved['image_publish_rate'],
            )
        return SetParametersResult(successful=True)

    def _publish_status(self) -> None:
        server = self.server
        self.emit(protocol.status(
            robot_id=self.robot_id,
            mode=self.mode,
            nav_active=self.nav_active,
            estop=self.estop,
            clients=server.clients if server else 0,
            stamp=self.get_clock().now().nanoseconds / 1e9,
            preset=self.registry.applied_preset,
        ))

    # ---- Web → ROS ---------------------------------------------------------

    async def on_client_message(self, client: Client, message: dict[str, Any]) -> None:
        """認証済みクライアントからのフレームを捌く。

        まだ何も実装していない type は、黙って無視せず「未実装」と返す。
        黙って捨てると UI 側が「送ったのに効かない」理由を追えない。
        """
        kind = message['type']
        if kind == protocol.MSG_HEARTBEAT:
            # #12 でハートビート監視に繋ぐ。いまは受理だけする。
            return
        raise protocol.ProtocolError(f'{kind} はまだ実装していない')

    async def on_client_connect(self, client: Client) -> None:
        """認証直後に現在の状態をまとめて投げる。

        次の配信周期を待たせないためだけではない。**costmap は保持している
        ものを配らないと永久に届かない**（Nav2 は全量を latched で 1 回しか
        出さない。ADR-0002）。
        """
        server = self.server
        await asyncio.sleep(0)  # ハンドラを await 可能に保つ

        self._send_snapshot(client)

        client.enqueue(protocol.safe_encode(protocol.status(
            robot_id=self.robot_id,
            mode=self.mode,
            nav_active=self.nav_active,
            estop=self.estop,
            clients=server.clients if server else 1,
            stamp=self.get_clock().now().nanoseconds / 1e9,
            preset=self.registry.applied_preset,
        )))

    def _send_snapshot(self, client: Client) -> None:
        """いま保持している状態のうち、そのクライアントが購読中のものを配る。"""
        for frame in self.telemetry.snapshot():
            if client.wants(frame['type']):
                client.enqueue(protocol.safe_encode(frame))

    async def on_client_subscribe(self, client: Client) -> None:
        """購読を変えた直後に現在の状態を配り直す。

        後から costmap を購読したクライアントに全量を届けるため。Nav2 は
        全量を二度と publish しないので、待っても来ない（ADR-0002）。
        """
        await asyncio.sleep(0)
        self._send_snapshot(client)

    async def on_client_disconnect(self, client: Client) -> None:
        """接続が切れたときの後始末。

        **ここで手動速度をゼロにするのは #12 の役目だが、asyncio 側だけに
        頼らないこと。** 切断イベントが来ない切れ方（電源断、Wi-Fi 消失）が
        あるので、ROS タイマーのハートビート監視が本命になる。
        """
        return


def _read_token(node: Node) -> str:
    token = os.environ.get('WHILL_GATEWAY_TOKEN', '')
    if not token:
        # Phase 0 では警告だけだった。無認証で待ち受ける状態を作らないため、
        # ここで起動を止める。LAN 限定とはいえ、研究室の LAN は共有されている。
        node.get_logger().fatal(
            'WHILL_GATEWAY_TOKEN が未設定。gateway は無認証では起動しない。\n'
            '  例: export WHILL_GATEWAY_TOKEN=$(openssl rand -hex 16)')
        raise SystemExit(2)
    if len(token) < 8:
        node.get_logger().fatal('WHILL_GATEWAY_TOKEN が短すぎる（8 文字以上にすること）')
        raise SystemExit(2)
    return token


async def _serve(node: Gateway, token: str) -> None:
    node._loop = asyncio.get_running_loop()
    node.server = GatewayServer(
        token=token,
        robot_id=node.robot_id,
        mode=node.mode,
        on_message=node.on_client_message,
        on_connect=node.on_client_connect,
        on_subscribe=node.on_client_subscribe,
        on_disconnect=node.on_client_disconnect,
    )
    await node.server.serve(node.bind_address, node.port)
    node.get_logger().info(
        f'ws://{node.bind_address}:{node.port} で待ち受け中 '
        f'(robot={node.robot_id}, mode={node.mode})')
    # サーバは close されるまで動き続ける。ここで無限に待つ。
    await asyncio.Event().wait()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = Gateway()
    token = _read_token(node)

    executor = SingleThreadedExecutor()
    executor.add_node(node)
    # ROS を別スレッドで回す。daemon にしておかないと、asyncio 側が
    # 終わってもプロセスが残る。
    spinner = threading.Thread(target=executor.spin, daemon=True, name='rclpy-spin')
    spinner.start()

    try:
        asyncio.run(_serve(node, token))
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
