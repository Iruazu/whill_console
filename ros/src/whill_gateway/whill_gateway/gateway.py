"""whill_gateway — ROS と Web の唯一の接点。

Phase 0 時点で実装済みなのは「registry からのパラメータ宣言」と「ヘルスチェック」まで。
WebSocket サーバ本体（costmap / path / pose の配信、param set、仮想障害物 CRUD、
手動速度指令、E-stop）は Phase 2 のスコープ。

このノードが Phase 0 に存在する理由は 2 つ:
  1. ParameterDescriptor 経由の宣言が registry から実際に通ることを、
     Phase 2 を待たずに検証しておくため（原則 6 の配線確認）
  2. bringup の gateway:=true の経路を空でも通しておき、Phase 2 で
     中身を差し替えるだけにするため
"""

from __future__ import annotations

import os

import rclpy
from rclpy.node import Node

from whill_params import registry as reg
from whill_params.descriptors import declare_from_registry


class Gateway(Node):

    def __init__(self) -> None:
        super().__init__('whill_gateway')

        self.declare_parameter('robot_id', 'cr2-01')
        self.declare_parameter('mode', 'mock')
        robot_id = self.get_parameter('robot_id').value
        mode = self.get_parameter('mode').value

        self.registry = reg.load(robot_id)
        declared = declare_from_registry(self, self.registry, node_name='whill_gateway')
        self.get_logger().info(
            f'registry から {len(declared)} 個のパラメータを宣言した: {declared}')

        # 認証は固定トークン 1 本のみ。これ以上の防御は無いので LAN 限定で使う。
        # 未設定で起動できてしまうと Phase 2 で無認証のまま繋がるため、
        # ここで警告を出しておく（Phase 2 では起動を止める）。
        if not os.environ.get('WHILL_GATEWAY_TOKEN'):
            self.get_logger().warning(
                'WHILL_GATEWAY_TOKEN が未設定。Phase 2 で WebSocket を有効にする前に必ず設定すること')

        bind = self.get_parameter('bind_address').value
        port = self.get_parameter('port').value
        self.get_logger().info(
            f'robot={robot_id} mode={mode} — WebSocket は Phase 2 で実装 '
            f'(予定バインド先 ws://{bind}:{port})')

        # live で変更できるパラメータの一覧は UI が引く情報。Phase 2 で
        # WebSocket に載せる前に、ログで中身を確認できるようにしておく。
        self.get_logger().info(
            f'live 変更可能: {len(self.registry.live_keys())} 件 / '
            f'全 {len(self.registry.specs)} 件')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = Gateway()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
