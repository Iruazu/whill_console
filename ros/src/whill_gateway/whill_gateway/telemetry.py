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
from sensor_msgs.msg import CompressedImage, LaserScan
from tf2_msgs.msg import TFMessage

from whill_gateway import costmap_codec, protocol
from whill_gateway.tf_tree import TfTree

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

# /scan と圧縮画像は best-effort sensor-data QoS で出る。reliable で購読すると
# QoS 不一致で 1 通も届かない（繋がらないのではなく、静かに何も来ない）。
SENSOR_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
)

SCAN_MAX_POINTS = 360
"""1 スキャンで送る点の上限。

VLP-16 は 10 Hz で約 900 点。俯瞰図の背景としてはそこまで要らないうえ、
JSON で 900 個の float を毎回送ると帯域を無駄にする。等間隔に間引く。
細かい形状が見たいときは Foxglove で点群を見ること（設計原則 2）。
"""

COSTMAP_SCOPES = {
    'local': '/local_costmap/costmap',
    'global': '/global_costmap/costmap',
}


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    import math
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _stamp_seconds(header) -> float:
    return header.stamp.sec + header.stamp.nanosec / 1e9


JITTER_TOLERANCE = 0.1
"""到着の揺れをどれだけ許すか（周期に対する割合）。

**入力と同じレートに制限すると、揺れのぶんだけ落ちる。** 6 Hz で出るカメラを
6 Hz に制限したら、実測 4.3 Hz しか通らなかった（到着が 1/6 秒をわずかに
下回るたびに 1 枚落ちるため）。レート制限は帯域を守るためのものであって、
宣言どおりのレートで来た入力を 3 割捨てるのは目的から外れている。

1 割にしてあるのは、制限を超えて増える量を 1 割で抑えるため。
"""


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
        # 周期ちょうどで来たものを落とさない（JITTER_TOLERANCE）。
        if self._last is None or now - self._last >= self.period * (1.0 - JITTER_TOLERANCE):
            self._last = now
            return True
        return False

    def set_rate(self, hz: float) -> None:
        self.period = 1.0 / hz if hz > 0 else 0.0


class Telemetry:
    """購読とフレーム化。ROS のスレッドで動く。"""

    def __init__(self, node: Node, emit: Callable[[dict[str, Any]], None],
                 *, costmap_hz: float, pose_hz: float, scan_hz: float,
                 image_hz: float, max_cells: int = costmap_codec.DEFAULT_MAX_CELLS,
                 wall_clock=None, tf_tree: TfTree | None = None) -> None:
        self.max_cells = max_cells
        self.node = node
        # レート制限は**実時間**で測る。ブラウザへの帯域を守るためのものなので、
        # sim 時計が止まったり倍速で進んだりするのに引きずられてはいけない。
        # replay で sim 時計が進まず、最初の 1 通以降が全部止まった実績がある。
        self._wall = wall_clock
        self.emit = emit
        self._seq = 0
        self._costmap_limit = {scope: RateLimiter(costmap_hz) for scope in COSTMAP_SCOPES}
        self._update_limit = {scope: RateLimiter(costmap_hz) for scope in COSTMAP_SCOPES}
        self._pose_limit = RateLimiter(pose_hz)
        self._scan_limit = RateLimiter(scan_hz)
        self._image_limit = RateLimiter(image_hz)
        # 全量を受けた scope だけ部分更新を流す。全量を持たないクライアントに
        # 部分更新だけ送っても貼り込む先が無い。
        self._have_full: dict[str, int] = {}
        self._decimation: dict[str, int] = {}
        # **最新の全量フレームを保持する。**
        # Nav2 は全量を latched で 1 回しか出さない（ADR-0002）。gateway が
        # 起動した瞬間に受け取ったきりなので、後から繋いだクライアントには
        # 何も届かない。実際に、gateway 起動時は asyncio のループがまだ
        # 無くて emit が捨てられ、costmap が永久に届かない状態になった。
        # 保持しておき、接続時にまとめて配る。
        self._latest_full: dict[str, dict[str, Any]] = {}
        self._latest_pose: dict[str, Any] | None = None
        self._latest_path: dict[str, Any] | None = None
        self._latest_scan: dict[str, Any] | None = None
        self._tf = tf_tree if tf_tree is not None else TfTree()

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
        # /scan は best-effort sensor-data QoS で出る。reliable で購読すると
        # 繋がらない（既定の QoS 不一致）。
        node.create_subscription(LaserScan, '/scan', self._on_scan, SENSOR_QOS)
        node.create_subscription(DiagnosticArray, '/diagnostics', self._on_diagnostics, 10)

        # tf は要約だけ流す。変換行列そのものは送らない（3D は Foxglove に
        # 委譲する方針。設計原則 2）。
        # /tf と /tf_static は分けて受ける。止まっていて正常な辺（static）と
        # 止まったら故障の辺を区別するため（#51）。
        node.create_subscription(
            TFMessage, '/tf', lambda msg: self._on_tf(msg, static=False), 50)
        node.create_subscription(
            TFMessage, '/tf_static', lambda msg: self._on_tf(msg, static=True),
            STATIC_TF_QOS)

        # **best-effort で購読する**（#52）。depth だけ渡すと既定の RELIABLE になり、
        # best-effort で出すカメラから 1 通も届かない。Phase 2 からずっとそうで、
        # 実測で ROS 側 6 Hz・WebSocket 0 通だった。/scan と同じ理由で揃える。
        # best-effort の購読は reliable の publisher とも繋がるので、ドライバの
        # 設定がどちらでも届く。
        node.create_subscription(
            CompressedImage, '/camera/camera/color/image_raw/compressed',
            self._on_image, SENSOR_QOS)

    def set_rates(self, *, costmap_hz: float, pose_hz: float, scan_hz: float,
                  image_hz: float) -> None:
        """live パラメータの変更を反映する。"""
        for limiter in self._costmap_limit.values():
            limiter.set_rate(costmap_hz)
        for limiter in self._update_limit.values():
            limiter.set_rate(costmap_hz)
        self._pose_limit.set_rate(pose_hz)
        self._scan_limit.set_rate(scan_hz)
        self._image_limit.set_rate(image_hz)

    def _now(self) -> float:
        clock = self._wall if self._wall is not None else self.node.get_clock()
        return clock.now().nanoseconds / 1e9

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
            max_cells=self.max_cells,
        )
        self._decimation[scope] = frame['decimation']
        self._latest_full[scope] = frame
        self.emit(frame)

    def _on_costmap_update(self, scope: str, msg: OccupancyGridUpdate) -> None:
        # 全量をまだ配っていない scope の部分更新は捨てる。貼り込む先が無い。
        if scope not in self._have_full:
            return
        # 間引いて送った格子には、元の解像度の部分更新を貼れない。
        # 貼ると座標がずれた絵になるので、送らない。次の全量で追いつく。
        if self._decimation.get(scope, 1) > 1:
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

    # ---- LiDAR -------------------------------------------------------------

    def _on_scan(self, msg: LaserScan) -> None:
        """LaserScan を俯瞰図用に間引いて送る。

        角度は `angle_min` と `angle_increment` から復元できるので送らない。
        間引いたぶん increment が変わる点に注意（`angle_increment` は
        間引き後の値を入れる）。

        無限遠と range 外は null にする。0 を入れると「原点に障害物がある」
        ように描かれる。
        """
        if not self._scan_limit.allow(self._now()):
            return

        ranges = list(msg.ranges)
        if not ranges:
            return
        step = max(1, (len(ranges) + SCAN_MAX_POINTS - 1) // SCAN_MAX_POINTS)
        sampled = ranges[::step]

        cleaned: list[float | None] = []
        for value in sampled:
            if value != value or value in (float('inf'), float('-inf')):
                cleaned.append(None)
            elif value < msg.range_min or value > msg.range_max:
                cleaned.append(None)
            else:
                # cm 単位に丸める。俯瞰図の解像度は costmap の 5 cm なので
                # これ以上の精度は帯域の無駄。
                cleaned.append(round(float(value), 2))

        self._latest_scan = {
            'type': protocol.MSG_SCAN,
            'frame_id': msg.header.frame_id,
            'angle_min': float(msg.angle_min),
            'angle_increment': float(msg.angle_increment) * step,
            'range_max': float(msg.range_max),
            'ranges': cleaned,
            'stamp': _stamp_seconds(msg.header),
        }
        self.emit(self._latest_scan)

    # ---- tf / 診断 ---------------------------------------------------------

    def _on_tf(self, msg: TFMessage, *, static: bool) -> None:
        """辺ごとに、最後に届いた実時間を覚える（`tf_tree.py`）。

        到着の時刻は **実時間** で取る。止まったかどうかを見たいので、bag の
        stamp や sim 時計では測らない（sim 時計ごと止まると古さが 0 のまま）。
        """
        now = self._now()
        for transform in msg.transforms:
            self._tf.observe(transform.header.frame_id, transform.child_frame_id,
                             static=static, wall_sec=now)

    def publish_tf_summary(self) -> None:
        """タイマーから呼ぶ。**変化が無くても流す。**

        以前は親子関係が変わったときだけ流していた。TF が止まっても親子関係は
        変わらないので、止まったことが画面に届かなかった。
        """
        if self._tf.is_empty and not self._tf.expects_anything:
            return
        self.emit(self._tf.frame(self._now()))

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
        if self._latest_scan is not None:
            frames.append(self._latest_scan)
        if not self._tf.is_empty:
            frames.append(self._tf.frame(self._now()))
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
