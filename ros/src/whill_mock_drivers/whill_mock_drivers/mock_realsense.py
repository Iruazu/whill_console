"""D435 のモック。CompressedImage と CameraInfo を出す。

画像は合成のテストパターン。フレーム番号と時刻を焼き込んであるので、Web 側で
「止まっている絵」と「更新されている絵」を目視で区別できる。camera パネル
（Phase 6）と gateway のレート制限の検証がここでの用途。

realsense は cr2-base.yaml で enabled_by_default: false。CPU を食うので、
必要なときだけ launch 引数 use_camera:=true で上げる。
"""

from __future__ import annotations

import cv2
import numpy as np
import rclpy
from sensor_msgs.msg import CameraInfo, CompressedImage

from whill_mock_drivers.common import SENSOR_QOS, MockDriverNode

TOPIC_IMAGE = '/camera/camera/color/image_raw/compressed'
TOPIC_INFO = '/camera/camera/color/camera_info'


class MockRealsense(MockDriverNode):

    driver_name = 'realsense'

    def __init__(self) -> None:
        super().__init__('mock_realsense')

        self.declare_parameter('frame_id', 'camera_color_optical_frame')
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('jpeg_quality', 70)

        self.frame_id = self.get_parameter('frame_id').value
        self.width = int(self.get_parameter('width').value)
        self.height = int(self.get_parameter('height').value)
        self.quality = int(self.get_parameter('jpeg_quality').value)

        self.image_pub = self.create_publisher(CompressedImage, TOPIC_IMAGE, SENSOR_QOS)
        self.info_pub = self.create_publisher(CameraInfo, TOPIC_INFO, SENSOR_QOS)

        self.frame = 0
        self.pattern = self._build_pattern()

        period = self.period_for(TOPIC_IMAGE, 6.0)
        self.timer = self.create_timer(period, self._tick)
        self.get_logger().info(
            f'{self.width}x{self.height} JPEG を {1.0 / period:.1f} Hz で配信')

    def _build_pattern(self) -> np.ndarray:
        """静的な背景。毎フレーム作り直すと 6 Hz でも無駄に CPU を使う。"""
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        bar_width = max(1, self.width // 8)
        colors = [(255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0),
                  (255, 0, 255), (0, 0, 255), (255, 0, 0), (0, 0, 0)]
        for index, color in enumerate(colors):
            x0 = index * bar_width
            img[:self.height // 2, x0:x0 + bar_width] = color
        cv2.putText(img, 'MOCK - NOT A REAL CAMERA',
                    (12, self.height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (255, 255, 255), 2, cv2.LINE_AA)
        return img

    def _tick(self) -> None:
        now = self.get_clock().now()
        stamp = now.to_msg()
        self.frame += 1

        img = self.pattern.copy()
        label = f'frame {self.frame:06d}  t={stamp.sec}.{stamp.nanosec // 1_000_000:03d}'
        cv2.putText(img, label, (12, self.height // 2 + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        # 静止画と区別できるよう、フレームごとに動く指標を入れる
        cx = int((self.frame * 7) % self.width)
        cv2.circle(img, (cx, self.height - 60), 12, (0, 165, 255), -1)

        ok, buf = cv2.imencode('.jpg', img,
                               [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
        if not ok:
            self.get_logger().warning('JPEG エンコードに失敗した')
            return

        msg = CompressedImage()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        msg.format = 'jpeg'
        msg.data = buf.tobytes()
        self.image_pub.publish(msg)

        self._publish_info(stamp)

    def _publish_info(self, stamp) -> None:
        info = CameraInfo()
        info.header.stamp = stamp
        info.header.frame_id = self.frame_id
        info.width = self.width
        info.height = self.height
        info.distortion_model = 'plumb_bob'
        info.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        # D435 の 640x480 color におおよそ合う内部パラメータ。実機の値は
        # 実機復帰後に rs-enumerate-devices で置き換える（実機検証待ち）。
        fx = fy = 615.0
        cx = self.width / 2.0
        cy = self.height / 2.0
        info.k = [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0]
        info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        info.p = [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.info_pub.publish(info)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MockRealsense()
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
