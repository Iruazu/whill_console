"""D435 のモック。CompressedImage と CameraInfo を出す。

画像は合成のテストパターン。フレーム番号と時刻を焼き込んであるので、Web 側で
「止まっている絵」と「更新されている絵」を目視で区別できる。camera パネル
（Phase 6）と gateway のレート制限の検証がここでの用途。

realsense は cr2-base.yaml で enabled_by_default: false。CPU を食うので、
必要なときだけ launch 引数 use_camera:=true で上げる。

## パラメータ名は実ドライバに合わせる（#53）

以前は `width` / `height` / `jpeg_quality` という独自の名前だった。実ドライバ
（realsense2_camera 4.55.1）は `rgb_camera.color_profile` などなので、
**独自の名前のままだと params.yaml に実機の名前を書いた瞬間、mock では
「知らないパラメータ」になり、実機なしで一度も動かないスライダーができる。**
名前も、ノード名（`/camera/camera`）も実ドライバに揃えてある。

露出は合成画像の明るさに効かせる。**効いたことが画像で分かる**ようにしないと、
スライダーが実際に届いているかを mock で確かめられない。
"""

from __future__ import annotations

import cv2
import numpy as np
import rclpy
from sensor_msgs.msg import CameraInfo, CompressedImage

from rcl_interfaces.msg import ParameterDescriptor, IntegerRange, SetParametersResult

from whill_mock_drivers.common import SENSOR_QOS, MockDriverNode

TOPIC_IMAGE = '/camera/camera/color/image_raw/compressed'
TOPIC_INFO = '/camera/camera/color/camera_info'

DEFAULT_PROFILE = '640,480,6'
"""`幅,高さ,FPS`。実ドライバの既定は `0,0,0`（ドライバ任せ）だが、モックは
自分で絵を作るので決めておく必要がある。値は params.yaml と揃えること。"""

NOMINAL_EXPOSURE_US = 156
"""この露出で「ちょうどよい明るさ」になる。自動露出のときもこの明るさで出す。"""


def parse_profile(text: str) -> tuple[int, int, float]:
    """`幅,高さ,FPS` を読む。壊れていたら ValueError。

    実ドライバは文字列 1 本でこの 3 つを受ける。分解して持つと実機と形が
    変わるので、文字列のまま受けてここで解く。
    """
    parts = [item.strip() for item in text.split(',')]
    if len(parts) != 3:
        raise ValueError(f'color_profile は "幅,高さ,FPS" の形にすること: {text!r}')
    width, height, fps = int(parts[0]), int(parts[1]), float(parts[2])
    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError(f'color_profile の値は全て正であること: {text!r}')
    return width, height, fps


def exposure_gain(*, auto: bool, exposure_us: int) -> float:
    """露出から明るさの倍率。自動露出のときは 1.0（ドライバが合わせる想定）。"""
    if auto:
        return 1.0
    return exposure_us / NOMINAL_EXPOSURE_US


class MockRealsense(MockDriverNode):

    driver_name = 'realsense'

    def __init__(self) -> None:
        # 実ドライバと同じ /camera/camera。launch も宣言（cr2-base.yaml の
        # drivers.realsense.ros_node）からこの名前で起動する。
        super().__init__('camera', namespace='camera')

        self.declare_parameter('frame_id', 'camera_color_optical_frame')
        # 名前は実ドライバ（rs_launch.py）と一字一句同じにすること。
        self.declare_parameter(
            'rgb_camera.color_profile', DEFAULT_PROFILE,
            ParameterDescriptor(description='カラーストリームの 幅,高さ,FPS'))
        self.declare_parameter(
            'rgb_camera.enable_auto_exposure', True,
            ParameterDescriptor(description='カラー画像の自動露出'))
        self.declare_parameter(
            'rgb_camera.exposure', NOMINAL_EXPOSURE_US,
            ParameterDescriptor(
                description='カラー画像の露出時間 [us]。自動露出が true なら効かない',
                integer_range=[IntegerRange(from_value=1, to_value=10000, step=1)]))
        self.declare_parameter('jpeg_quality', 70)

        self.frame_id = self.get_parameter('frame_id').value
        self.width, self.height, self.fps = parse_profile(
            str(self.get_parameter('rgb_camera.color_profile').value))
        self.auto_exposure = bool(
            self.get_parameter('rgb_camera.enable_auto_exposure').value)
        self.exposure_us = int(self.get_parameter('rgb_camera.exposure').value)
        self.quality = int(self.get_parameter('jpeg_quality').value)

        self.image_pub = self.create_publisher(CompressedImage, TOPIC_IMAGE, SENSOR_QOS)
        self.info_pub = self.create_publisher(CameraInfo, TOPIC_INFO, SENSOR_QOS)

        self.frame = 0
        self.pattern = self._build_pattern()

        # 宣言レート（cr2-base.yaml）と profile の FPS が食い違ったら宣言を優先する。
        # 宣言は whill doctor が突き合わせる契約なので、こちらを正とする。
        declared = self.rate_for(TOPIC_IMAGE, 6.0)
        if abs(declared - self.fps) > 0.01:
            self.get_logger().warning(
                f'color_profile の FPS {self.fps} は宣言の {declared} Hz と違う。'
                f'宣言に従う（cr2-base.yaml が契約）')
        self.timer = self.create_timer(1.0 / declared, self._tick)
        self.add_on_set_parameters_callback(self._on_set_parameters)
        self.get_logger().info(
            f'{self.width}x{self.height} JPEG を {declared:.1f} Hz で配信'
            f'（露出 {"auto" if self.auto_exposure else f"{self.exposure_us} us"}）')

    # ---- パラメータ --------------------------------------------------------

    def _on_set_parameters(self, params) -> SetParametersResult:
        """実ドライバと同じ名前で受けて、絵に反映する。

        **壊れた値は拒否して、前の値のまま動き続ける。** 受理してから落ちると、
        「スライダーを動かしたらカメラが消えた」になる。
        """
        pending = {p.name: p.value for p in params}
        try:
            profile = pending.get('rgb_camera.color_profile')
            size = parse_profile(str(profile)) if profile is not None else None
        except ValueError as exc:
            return SetParametersResult(successful=False, reason=str(exc))

        if size is not None:
            self.width, self.height, self.fps = size
            # 背景は作り直す。大きさが変わったまま古い絵を使うと、次の
            # imencode で形が合わずに落ちる。
            self.pattern = self._build_pattern()
        if 'rgb_camera.enable_auto_exposure' in pending:
            self.auto_exposure = bool(pending['rgb_camera.enable_auto_exposure'])
        if 'rgb_camera.exposure' in pending:
            self.exposure_us = int(pending['rgb_camera.exposure'])
        if 'jpeg_quality' in pending:
            self.quality = int(pending['jpeg_quality'])
        return SetParametersResult(successful=True)

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

        # 露出を明るさに効かせる。効いたことが画像で分かるようにするため
        # （スライダーが実際に届いたかを mock で確かめられる）。
        gain = exposure_gain(auto=self.auto_exposure, exposure_us=self.exposure_us)
        if abs(gain - 1.0) > 1e-6:
            img = cv2.convertScaleAbs(img, alpha=gain, beta=0)

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
