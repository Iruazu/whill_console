"""ROS のトピックを購読して、Web へ流すフレームに変換する。

`Telemetry` は ROS 側（executor スレッド）で動き、出来上がったフレームを
`emit` コールバックに渡す。`emit` の中身は gateway が用意した
`call_soon_threadsafe` 経由のブロードキャスト。

変換のうち純粋な部分は `costmap_codec.py` に置いてある。ここは購読の配線と
レート制限だけを持つ。
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import PoseWithCovarianceStamped
from map_msgs.msg import OccupancyGridUpdate
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import CompressedImage
from tf2_msgs.msg import TFMessage

from whill_gateway import costmap_codec, protocol

# Nav2 の costmap は latched (transient local) で出る。既定の volatile で
# 購読すると、接続前に publish された全量を取りこぼして永久に絵が出ない。
LATCHED_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)

# /tf_static は「1 つの transform につき 1 メッセージ」で latched publish される
# ことがある（static_transform_publisher がまさにそう）。depth 1 で購読すると
# 最後の 1 本しか残らず、tf ツリーが歯抜けになる。実測で 2 フレームしか
# 取れなかったのがこれ。
STATIC_TF_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=100,
)

COSTMAP_SCOPES = {
    'local': '/local_costmap/costmap',
    'global': '/global_costmap/costmap',
}


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    import math
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _stamp_seconds(header) -> float:
    return header.stamp.sec + header.stamp.nanosec / 1e9


class RateLimiter:
    """一定間隔でしか通さない。時刻は呼び出し側が渡す。

    実時間を内部で読まないのは、テストを決定的にするため。
    """

    def __init__(self, hz: float) -> None:
        self.period = 1.0 / hz if hz > 0 else 0.0
        self._last: float | None = None

    def allow(self, now: float) -> bool:
        if self.period <= 0.0:
            return True
        if self._last is None or now - self._last >= self.period:
            self._last = now
            return True
        return False

    def set_rate(self, hz: float) -> None:
        self.period = 1.0 / hz if hz > 0 else 0.0


class Telemetry:
    """購読とフレーム化。ROS のスレッドで動く。"""

    def __init__(self, node: Node, emit: Callable[[dict[str, Any]], None],
                 *, costmap_hz: float, pose_hz: float, image_hz: float) -> None:
        self.node = node
        self.emit = emit
        self._seq = 0
        self._costmap_limit = {scope: RateLimiter(costmap_hz) for scope in COSTMAP_SCOPES}
        self._update_limit = {scope: RateLimiter(costmap_hz) for scope in COSTMAP_SCOPES}
        self._pose_limit = RateLimiter(pose_hz)
        self._image_limit = RateLimiter(image_hz)
        # 全量を受けた scope だけ部分更新を流す。全量を持たないクライアントに
        # 部分更新だけ送っても貼り込む先が無い。
        self._have_full: dict[str, int] = {}
        # **最新の全量フレームを保持する。**
        # Nav2 は全量を latched で 1 回しか出さない（ADR-0002）。gateway が
        # 起動した瞬間に受け取ったきりなので、後から繋いだクライアントには
        # 何も届かない。実際に、gateway 起動時は asyncio のループがまだ
        # 無くて emit が捨てられ、costmap が永久に届かない状態になった。
        # 保持しておき、接続時にまとめて配る。
        self._latest_full: dict[str, dict[str, Any]] = {}
        self._latest_pose: dict[str, Any] | None = None
        self._latest_path: dict[str, Any] | None = None
        self._tf_parents: dict[str, str] = {}
        self._tf_dirty = False

        self._subscribe()

    # ---- 購読 --------------------------------------------------------------

    def _subscribe(self) -> None:
        node = self.node
        for scope, topic in COSTMAP_SCOPES.items():
            node.create_subscription(
                OccupancyGrid, topic,
                lambda msg, s=scope: self._on_costmap(s, msg), LATCHED_QOS)
            node.create_subscription(
                OccupancyGridUpdate, f'{topic}_updates',
                lambda msg, s=scope: self._on_costmap_update(s, msg), 10)

        # 実機は scan-to-map localizer の /pcl_pose、mock は EKF の
        # /odometry/filtered。どちらも購読して、来たほうを流す。
        node.create_subscription(
            PoseWithCovarianceStamped, '/pcl_pose', self._on_pcl_pose, 10)
        node.create_subscription(
            Odometry, '/odometry/filtered', self._on_odometry, 10)

        node.create_subscription(Path, '/plan', self._on_path, 10)
        node.create_subscription(DiagnosticArray, '/diagnostics', self._on_diagnostics, 10)

        # tf は要約だけ流す。変換行列そのものは送らない（3D は Foxglove に
        # 委譲する方針。設計原則 2）。
        node.create_subscription(TFMessage, '/tf', self._on_tf, 50)
        node.create_subscription(TFMessage, '/tf_static', self._on_tf, STATIC_TF_QOS)

        node.create_subscription(
            CompressedImage, '/camera/camera/color/image_raw/compressed',
            self._on_image, 5)

    def set_rates(self, *, costmap_hz: float, pose_hz: float, image_hz: float) -> None:
        """live パラメータの変更を反映する。"""
        for limiter in self._costmap_limit.values():
            limiter.set_rate(costmap_hz)
        for limiter in self._update_limit.values():
            limiter.set_rate(costmap_hz)
        self._pose_limit.set_rate(pose_hz)
        self._image_limit.set_rate(image_hz)

    def _now(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1e9

    # ---- costmap -----------------------------------------------------------

    def _on_costmap(self, scope: str, msg: OccupancyGrid) -> None:
        if not self._costmap_limit[scope].allow(self._now()):
            return
        self._seq += 1
        self._have_full[scope] = self._seq
        frame = costmap_codec.costmap_frame(
            scope=scope,
            frame_id=msg.header.frame_id,
            resolution=msg.info.resolution,
            width=msg.info.width,
            height=msg.info.height,
            origin_x=msg.info.origin.position.x,
            origin_y=msg.info.origin.position.y,
            cells=list(msg.data),
            stamp=_stamp_seconds(msg.header),
            seq=self._seq,
        )
        self._latest_full[scope] = frame
        self.emit(frame)

    def _on_costmap_update(self, scope: str, msg: OccupancyGridUpdate) -> None:
        # 全量をまだ配っていない scope の部分更新は捨てる。貼り込む先が無い。
        if scope not in self._have_full:
            return
        if not self._update_limit[scope].allow(self._now()):
            return
        self.emit(costmap_codec.costmap_update_frame(
            scope=scope,
            x=msg.x, y=msg.y, width=msg.width, height=msg.height,
            cells=list(msg.data),
            stamp=_stamp_seconds(msg.header),
            seq=self._have_full[scope],
        ))

    # ---- pose / path -------------------------------------------------------

    def _on_pcl_pose(self, msg: PoseWithCovarianceStamped) -> None:
        self._emit_pose(msg.header, msg.pose.pose, source='pcl_pose')

    def _on_odometry(self, msg: Odometry) -> None:
        self._emit_pose(msg.header, msg.pose.pose, source='odometry/filtered')

    def _emit_pose(self, header, pose, *, source: str) -> None:
        q = pose.orientation
        frame = {
            'type': protocol.MSG_POSE,
            'frame_id': header.frame_id,
            'source': source,
            'x': pose.position.x,
            'y': pose.position.y,
            'yaw': _yaw_from_quaternion(q.x, q.y, q.z, q.w),
            'stamp': _stamp_seconds(header),
        }
        # 保持は毎回更新する（接続時に配るのは最新であってほしい）。
        # 送信だけレート制限する。
        self._latest_pose = frame
        if self._pose_limit.allow(self._now()):
            self.emit(frame)

    def _on_path(self, msg: Path) -> None:
        frame = {
            'type': protocol.MSG_PATH,
            'frame_id': msg.header.frame_id,
            # 経路は点が多い。俯瞰図に描くだけなので x, y だけ送る。
            'points': [[p.pose.position.x, p.pose.position.y] for p in msg.poses],
            'stamp': _stamp_seconds(msg.header),
        }
        self._latest_path = frame
        self.emit(frame)

    # ---- tf / 診断 ---------------------------------------------------------

    def _on_tf(self, msg: TFMessage) -> None:
        """親子関係だけ覚える。変わったときだけ流す。

        毎フレーム送ると 50 Hz で同じ内容が流れる。tf パネルが見たいのは
        「どのフレームがどこに繋がっているか」であって、値の時系列ではない。
        """
        for transform in msg.transforms:
            child = transform.child_frame_id
            parent = transform.header.frame_id
            if self._tf_parents.get(child) != parent:
                self._tf_parents[child] = parent
                self._tf_dirty = True

    def publish_tf_summary(self) -> None:
        """タイマーから呼ぶ。変化が無ければ何もしない。"""
        if not self._tf_dirty:
            return
        self._tf_dirty = False
        self.emit({
            'type': protocol.MSG_TF,
            'parents': dict(self._tf_parents),
            'stamp': self._now(),
        })

    def snapshot(self) -> list[dict[str, Any]]:
        """繋いだ直後のクライアントへ配る、いま持っている状態。

        **これが無いと costmap が永久に届かない。** Nav2 は全量を latched で
        1 回しか出さないので、後から繋いだクライアントに配れるのは
        gateway が保持しているものだけ（ADR-0002）。

        部分更新は含めない。全量を送った直後なので、次の部分更新から
        貼り込めばよい。
        """
        frames: list[dict[str, Any]] = list(self._latest_full.values())
        if self._latest_pose is not None:
            frames.append(self._latest_pose)
        if self._latest_path is not None:
            frames.append(self._latest_path)
        if self._tf_parents:
            frames.append({
                'type': protocol.MSG_TF,
                'parents': dict(self._tf_parents),
                'stamp': self._now(),
            })
        return frames

    def _on_diagnostics(self, msg: DiagnosticArray) -> None:
        self.emit({
            'type': protocol.MSG_DIAGNOSTICS,
            'entries': [
                {
                    'name': status.name,
                    'level': int.from_bytes(status.level, 'big')
                    if isinstance(status.level, bytes) else int(status.level),
                    'message': status.message,
                }
                for status in msg.status
            ],
            'stamp': _stamp_seconds(msg.header),
        })

    # ---- 画像 --------------------------------------------------------------

    def _on_image(self, msg: CompressedImage) -> None:
        if not self._image_limit.allow(self._now()):
            return
        # base64 は 4/3 に膨らむ。JSON 1 本で通す設計（設計原則 1）の代償として
        # 受け入れる。帯域が問題なら image_publish_rate を下げること。
        self.emit({
            'type': protocol.MSG_IMAGE,
            'format': msg.format,
            'data': base64.b64encode(bytes(msg.data)).decode('ascii'),
            'stamp': _stamp_seconds(msg.header),
        })
