"""VLP-16 のモック。

合成した「廊下」を 16 リングでスキャンし、PointCloud2 と、その水平リングから
落とした LaserScan を出す。狙いは Nav2 の obstacle layer と gateway の
2D 俯瞰描画に実データと同じ形の入力を与えること。点群の中身の物理的正しさは
求めていない。

QoS は実機と同じ best-effort。ここを reliable にすると costmap 側の
QoS 不一致（実機で実際に踏んだ罠）をモックで再現できなくなる。
"""

from __future__ import annotations

import math

import numpy as np
import rclpy
from sensor_msgs.msg import LaserScan, PointCloud2
from sensor_msgs_py import point_cloud2

from whill_mock_drivers.common import SENSOR_QOS, MockDriverNode

RING_ELEVATIONS_DEG = np.arange(-15.0, 16.0, 2.0)
"""VLP-16 の 16 本の仰角（-15..+15 deg, 2 deg 間隔）。"""

AZIMUTH_STEP_DEG = 0.4
"""10 Hz 設定時の実機の方位分解能に相当。"""


class MockVelodyne(MockDriverNode):

    driver_name = 'velodyne'

    def __init__(self) -> None:
        super().__init__('mock_velodyne')

        self.declare_parameter('frame_id', 'velodyne')
        self.declare_parameter('corridor_half_width', 2.5)
        self.declare_parameter('corridor_length', 20.0)
        self.declare_parameter('range_noise_stddev', 0.02)
        self.declare_parameter('obstacle_x', 6.0)
        self.declare_parameter('obstacle_y', 0.8)
        self.declare_parameter('obstacle_radius', 0.3)

        self.frame_id = self.get_parameter('frame_id').value
        self.half_width = float(self.get_parameter('corridor_half_width').value)
        self.length = float(self.get_parameter('corridor_length').value)
        self.noise = float(self.get_parameter('range_noise_stddev').value)

        self.cloud_pub = self.create_publisher(
            PointCloud2, '/velodyne_points', SENSOR_QOS)
        self.scan_pub = self.create_publisher(LaserScan, '/scan', SENSOR_QOS)

        self.azimuths = np.deg2rad(np.arange(0.0, 360.0, AZIMUTH_STEP_DEG))
        self.elevations = np.deg2rad(RING_ELEVATIONS_DEG)
        # 乱数は毎スキャン引き直す必要がない。生成コストを抑えるため固定 seed で
        # ノイズ場を作り、スキャンごとに位相だけずらす。
        self.rng = np.random.default_rng(seed=20260910)

        period = self.period_for('/velodyne_points', 10.0)
        self.timer = self.create_timer(period, self._tick)
        self.get_logger().info(
            f'合成廊下 (半幅 {self.half_width} m, 全長 {self.length} m) を '
            f'{1.0 / period:.1f} Hz で配信')

    def _corridor_range(self, azimuth: np.ndarray) -> np.ndarray:
        """水平方位ごとの、廊下の壁までの距離。

        左右の壁（y = ±half_width）と前後の突き当たり（x = ±length/2）の
        うち最も近いものを返す、素朴な矩形レイキャスト。
        """
        cos_a = np.cos(azimuth)
        sin_a = np.sin(azimuth)
        eps = 1e-9

        # 各壁との交点までの距離。背面側の解は無限大にして捨てる。
        candidates = []
        for offset, comp in ((self.half_width, sin_a), (-self.half_width, sin_a)):
            t = np.where(np.abs(comp) > eps, offset / np.where(np.abs(comp) > eps, comp, eps),
                         np.inf)
            candidates.append(np.where(t > 0, t, np.inf))
        for offset, comp in ((self.length / 2.0, cos_a), (-self.length / 2.0, cos_a)):
            t = np.where(np.abs(comp) > eps, offset / np.where(np.abs(comp) > eps, comp, eps),
                         np.inf)
            candidates.append(np.where(t > 0, t, np.inf))

        ranges = np.min(np.stack(candidates), axis=0)

        # 前方に置いた円柱障害物。Nav2 が回避経路を出すかを見るために入れてある。
        ox = float(self.get_parameter('obstacle_x').value)
        oy = float(self.get_parameter('obstacle_y').value)
        orad = float(self.get_parameter('obstacle_radius').value)
        # 光線 (cos_a, sin_a) と中心 (ox, oy) 半径 orad の円の交差
        proj = ox * cos_a + oy * sin_a
        perp_sq = ox * ox + oy * oy - proj * proj
        hit = (perp_sq < orad * orad) & (proj > 0)
        depth = np.sqrt(np.clip(orad * orad - perp_sq, 0.0, None))
        obstacle_range = np.where(hit, proj - depth, np.inf)
        ranges = np.minimum(ranges, obstacle_range)

        return ranges + self.rng.normal(0.0, self.noise, size=ranges.shape)

    def _tick(self) -> None:
        stamp = self.get_clock().now().to_msg()
        horizontal = self._corridor_range(self.azimuths)

        # 仰角ごとに水平距離を伸ばして 3D 化する。仰角が急なリングは床/天井で
        # 早く当たるので、床(-0.8 m)と天井(+1.6 m)でクリップする。
        cos_e = np.cos(self.elevations)[:, None]
        sin_e = np.sin(self.elevations)[:, None]
        slant = horizontal[None, :] / np.clip(cos_e, 1e-3, None)

        z_at_slant = slant * sin_e
        floor_slant = np.where(sin_e < -1e-3, -0.8 / sin_e, np.inf)
        ceil_slant = np.where(sin_e > 1e-3, 1.6 / sin_e, np.inf)
        slant = np.minimum(slant, np.minimum(floor_slant, ceil_slant))

        xs = (slant * cos_e * np.cos(self.azimuths)[None, :]).ravel()
        ys = (slant * cos_e * np.sin(self.azimuths)[None, :]).ravel()
        zs = (slant * sin_e).ravel()
        del z_at_slant

        points = np.stack([xs, ys, zs], axis=1).astype(np.float32)
        finite = np.isfinite(points).all(axis=1)
        points = points[finite]

        header = PointCloud2().header
        header.stamp = stamp
        header.frame_id = self.frame_id
        cloud = point_cloud2.create_cloud_xyz32(header, points.tolist())
        self.cloud_pub.publish(cloud)

        self._publish_scan(stamp, horizontal)

    def _publish_scan(self, stamp, horizontal: np.ndarray) -> None:
        """水平リング相当を LaserScan として出す。

        Nav2 の costmap は /scan を見るので、点群と別に必要。実機構成では
        pointcloud_to_laserscan が担う変換を、モックでは直接生成している。
        """
        scan = LaserScan()
        scan.header.stamp = stamp
        scan.header.frame_id = self.frame_id
        scan.angle_min = 0.0
        scan.angle_max = float(2.0 * math.pi - math.radians(AZIMUTH_STEP_DEG))
        scan.angle_increment = float(math.radians(AZIMUTH_STEP_DEG))
        scan.time_increment = 0.0
        scan.scan_time = float(self.period_for('/scan', 10.0))
        scan.range_min = 0.4
        scan.range_max = 100.0
        clipped = np.clip(horizontal, scan.range_min, scan.range_max)
        scan.ranges = clipped.astype(np.float32).tolist()
        self.scan_pub.publish(scan)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MockVelodyne()
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
