"""9軸 IMU のモック。

/whill/odom の yaw に追従した姿勢を 100 Hz で出す。odom と独立に自走させないのは、
drivers パネルの yaw vs ndt 比較（localization 劣化の早期検知）を検証するとき、
「正常時は一致し、drift_rate を上げると乖離が育つ」という筋書きが必要なため。

温度は /imu/temperature に別トピックで出す。cr2-base.yaml の telemetry 宣言が
そのトピックを参照しているため、宣言と実装をここで一致させている。
"""

from __future__ import annotations

import math

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile
from sensor_msgs.msg import Imu, Temperature

from whill_mock_drivers.common import (
    SENSOR_QOS,
    MockDriverNode,
    quaternion_to_yaw,
    yaw_to_quaternion,
)

GRAVITY = 9.80665


class MockBno085(MockDriverNode):

    driver_name = 'bno085'

    def __init__(self) -> None:
        super().__init__('mock_bno085')

        self.declare_parameter('frame_id', self.hardware.get('frame_id', 'imu_link'))
        # deg/min。0 なら odom と完全一致。localization 劣化の UI を試すときに上げる。
        self.declare_parameter('drift_rate', 0.0)
        self.declare_parameter('gyro_noise_stddev', 0.005)
        self.declare_parameter('temperature_start', 34.0)

        self.frame_id = self.get_parameter('frame_id').value
        self.drift_rate = float(self.get_parameter('drift_rate').value)
        self.gyro_noise = float(self.get_parameter('gyro_noise_stddev').value)
        self.temperature = float(self.get_parameter('temperature_start').value)

        self.imu_pub = self.create_publisher(Imu, '/imu/data_rep145', SENSOR_QOS)
        self.temp_pub = self.create_publisher(Temperature, '/imu/temperature', SENSOR_QOS)
        self.odom_sub = self.create_subscription(
            Odometry, '/whill/odom', self._on_odom, QoSProfile(depth=10))

        self.odom_yaw = 0.0
        self.odom_wz = 0.0
        self.drift = 0.0
        self.rng_state = 0

        period = self.period_for('/imu/data_rep145', 100.0)
        self.last_tick = self.get_clock().now()
        self.timer = self.create_timer(period, self._tick)
        # 温度は 100 Hz で出す意味がないので 1 Hz に落とす
        self.temp_timer = self.create_timer(1.0, self._publish_temperature)
        self.get_logger().info(
            f'{1.0 / period:.0f} Hz, frame={self.frame_id}, drift={self.drift_rate} deg/min')

    def _on_odom(self, msg: Odometry) -> None:
        q = msg.pose.pose.orientation
        self.odom_yaw = quaternion_to_yaw(q.x, q.y, q.z, q.w)
        self.odom_wz = msg.twist.twist.angular.z

    def _noise(self, scale: float) -> float:
        """軽量な擬似乱数。numpy の RNG を 100 Hz で回すほどの精度は要らない。"""
        self.rng_state = (self.rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        return ((self.rng_state / 0x7FFFFFFF) - 0.5) * 2.0 * scale

    def _tick(self) -> None:
        now = self.get_clock().now()
        dt = (now - self.last_tick).nanoseconds / 1e9
        self.last_tick = now
        if dt <= 0.0:
            return

        self.drift += math.radians(self.drift_rate) * dt / 60.0
        yaw = self.odom_yaw + self.drift

        msg = Imu()
        msg.header.stamp = now.to_msg()
        msg.header.frame_id = self.frame_id
        qx, qy, qz, qw = yaw_to_quaternion(yaw)
        msg.orientation.x = qx
        msg.orientation.y = qy
        msg.orientation.z = qz
        msg.orientation.w = qw
        msg.angular_velocity.z = self.odom_wz + self._noise(self.gyro_noise)
        # 水平静置を仮定。EKF に「重力が入っている」ことを伝える必要がある。
        msg.linear_acceleration.z = GRAVITY + self._noise(0.02)

        # EKF が IMU を過信しないよう対角に分散を入れる。実機ドライバの値レンジは
        # 実機検証待ち（docs/open-questions.md）。
        msg.orientation_covariance[8] = 0.02
        msg.angular_velocity_covariance[8] = 0.001
        msg.linear_acceleration_covariance[0] = 0.05
        msg.linear_acceleration_covariance[4] = 0.05
        msg.linear_acceleration_covariance[8] = 0.05
        self.imu_pub.publish(msg)

    def _publish_temperature(self) -> None:
        # 走行するほど温まる、程度の粗い模擬。閾値 warn=60 crit=75 に届かせたい
        # ときは temperature_start を上げて起動する。
        self.temperature += 0.01 * abs(self.odom_wz) + 0.002
        msg = Temperature()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.temperature = float(self.temperature)
        msg.variance = 0.0
        self.temp_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MockBno085()
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
