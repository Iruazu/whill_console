"""WHILL 本体シリアルドライバのモック。

cmd_vel を差動二輪として積分し、/whill/odom と ModelCr2State を出す。
odom -> base_link の TF は publish しない。実機構成では robot_localization の
EKF がその TF を出しており、モックが同じ TF を出すと二重 publish で
TF ツリーが壊れるため（実機と同じ配線で上位を検証したい）。

実機の cold boot 手順（SetPower(ON) → SetJoystick(EnableUser)）は、
「起動直後は publish が始まらず、boot_delay 後に始まる」という
観測できる形だけ模す。上位が起動待ちを正しく扱えるかを検証するため。
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile
from whill_msgs.msg import ModelCr2State

from whill_mock_drivers.common import MockDriverNode, yaw_to_quaternion

WHEEL_SEPARATION = 0.52
"""m。CR2 の左右駆動輪間隔の概算。odom の角速度→車輪速の分解にだけ使う。"""

WHEEL_RADIUS = 0.13
"""m。motor_angle をそれらしく進めるためだけの値。"""


class MockWhillSerial(MockDriverNode):

    driver_name = 'whill_serial'

    def __init__(self) -> None:
        super().__init__('mock_whill_serial')

        self.declare_parameter('boot_delay', 2.0)
        self.declare_parameter('battery_start', 93.0)
        self.declare_parameter('battery_drain_per_min', 0.4)

        self.boot_delay = float(self.get_parameter('boot_delay').value)
        self.battery = float(self.get_parameter('battery_start').value)
        self.drain = float(self.get_parameter('battery_drain_per_min').value)

        # 実機は publish_interval_ms=400 → 2.5 Hz。個体 yaml の値を優先する。
        interval_ms = float(self.hardware.get('publish_interval_ms', 400))
        period = interval_ms / 1000.0

        qos = QoSProfile(depth=10)
        self.odom_pub = self.create_publisher(Odometry, '/whill/odom', qos)
        self.state_pub = self.create_publisher(
            ModelCr2State, '/whill/states/model_cr2', qos)
        self.cmd_sub = self.create_subscription(
            Twist, '/whill/controller/cmd_vel', self._on_cmd, qos)

        self.x = 0.0
        self.y = 0.0
        self.yaw = 0.0
        self.vx = 0.0
        self.wz = 0.0
        self.left_angle = 0.0
        self.right_angle = 0.0

        self.started_at = self.get_clock().now()
        self.last_tick = self.started_at
        self.streaming = False

        self.timer = self.create_timer(period, self._tick)
        self.get_logger().info(
            f'cold boot 模擬: {self.boot_delay:.1f} s 後に {1.0 / period:.1f} Hz で publish 開始')

    def _on_cmd(self, msg: Twist) -> None:
        # 実機の Mode 2 上限は約 1.1 m/s。上位が誤って大きい値を出したときの
        # 挙動を見たいので、ここでは弾かずに飽和させる（実機と同じ振る舞い）。
        self.vx = max(-1.1, min(1.1, msg.linear.x))
        self.wz = max(-2.0, min(2.0, msg.angular.z))

    def _tick(self) -> None:
        now = self.get_clock().now()
        if not self.streaming:
            if (now - self.started_at).nanoseconds < self.boot_delay * 1e9:
                return
            self.streaming = True
            self.get_logger().info('SetPower(ON) + SetJoystick(EnableUser) 相当 — streaming 開始')

        dt = (now - self.last_tick).nanoseconds / 1e9
        self.last_tick = now
        if dt <= 0.0:
            return

        self.yaw = math.atan2(math.sin(self.yaw + self.wz * dt),
                              math.cos(self.yaw + self.wz * dt))
        self.x += self.vx * math.cos(self.yaw) * dt
        self.y += self.vx * math.sin(self.yaw) * dt

        v_left = self.vx - self.wz * WHEEL_SEPARATION / 2.0
        v_right = self.vx + self.wz * WHEEL_SEPARATION / 2.0
        self.left_angle += v_left / WHEEL_RADIUS * dt
        self.right_angle += v_right / WHEEL_RADIUS * dt
        self.battery = max(0.0, self.battery - self.drain * dt / 60.0)

        self._publish_odom(now, v_left, v_right)
        self._publish_state(now, v_left, v_right)

    def _publish_odom(self, now, v_left: float, v_right: float) -> None:
        msg = Odometry()
        msg.header.stamp = now.to_msg()
        msg.header.frame_id = 'odom'
        msg.child_frame_id = 'base_link'
        msg.pose.pose.position.x = self.x
        msg.pose.pose.position.y = self.y
        qx, qy, qz, qw = yaw_to_quaternion(self.yaw)
        msg.pose.pose.orientation.x = qx
        msg.pose.pose.orientation.y = qy
        msg.pose.pose.orientation.z = qz
        msg.pose.pose.orientation.w = qw
        msg.twist.twist.linear.x = self.vx
        msg.twist.twist.angular.z = self.wz
        # 実機ドライバの共分散に合わせた粗い値。EKF が odom を過信しないよう
        # 対角にだけ入れる（オフダイアゴナルは実機ドライバも出していない）。
        msg.pose.covariance[0] = 0.05
        msg.pose.covariance[7] = 0.05
        msg.pose.covariance[35] = 0.10
        msg.twist.covariance[0] = 0.02
        msg.twist.covariance[35] = 0.05
        self.odom_pub.publish(msg)

    def _publish_state(self, now, v_left: float, v_right: float) -> None:
        msg = ModelCr2State()
        msg.header.stamp = now.to_msg()
        msg.header.frame_id = 'base_link'
        msg.battery_power = int(round(self.battery))
        msg.left_motor_angle = float(self.left_angle)
        msg.right_motor_angle = float(self.right_angle)
        msg.left_motor_speed = float(v_left / WHEEL_RADIUS)
        msg.right_motor_speed = float(v_right / WHEEL_RADIUS)
        # 電流は「速度に比例＋無負荷分」の粗い近似。閾値超えの UI 表示を
        # 検証したいときは cmd_vel を上限まで出せば warn 域に入る。
        msg.left_motor_current = float(abs(v_left) * 6.0 + 0.4)
        msg.right_motor_current = float(abs(v_right) * 6.0 + 0.4)
        msg.joystick_front = 0
        msg.joystick_side = 0
        msg.speed_mode_indicator = 2
        msg.power_on = True
        msg.error = False
        msg.error_code = 0
        self.state_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MockWhillSerial()
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
