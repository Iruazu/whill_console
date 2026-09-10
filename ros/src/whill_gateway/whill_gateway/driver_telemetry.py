"""telemetry 宣言どおりにトピックを購読する。

宣言の解釈・閾値・保持は `telemetry_spec.py`（rclpy 非依存）が持つ。ここは
ROS の配線だけ。

## メッセージ型はどこから来るか

`cr2-base.yaml` の `publishes` に `type` が書いてある。telemetry の `topic` を
そこから引いて `rosidl_runtime_py` で解決する。**publishes に無いトピックを
telemetry で参照している場合は起動時に落とす** — 宣言だけあって永久に値が
出ないより、なぜ出ないかがその場で分かるほうがよい。

## 購読は全部 best-effort にする

velodyne は `qos: sensor_data`、`/whill/states/model_cr2` は既定（reliable）と
publisher 側がまちまちだが、**best-effort な購読は reliable な publisher とも
互換**なので、こちらを best-effort に寄せれば QoS 不一致で 1 通も来ない事故
（K6 と同じ「静かに何も届かない」）が起きない。

テレメトリは現在値の表示で、1 通落ちても次が来る。信頼性を落とす代償が無い。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import Imu

from whill_gateway.telemetry_spec import (
    FIELD_RATE,
    TelemetryError,
    TelemetryStore,
    expected_drivers,
    extract,
    load_derived,
    load_specs,
)
from whill_gateway.yaw_vs_ndt import YawRateVsNdt

DERIVED_IMU_TOPIC = '/imu/data_rep145'
DERIVED_NDT_TOPIC = '/pcl_pose'
DERIVED_YAW_RATE = 'yaw_rate_vs_ndt'
"""派生テレメトリの名前。`cr2-base.yaml` の `derived_telemetry` と揃えること。

宣言に無い名前を計算しても、閾値も単位も付かないまま捨てられる。
"""

TELEMETRY_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
)


def _topic_types(base: dict[str, Any]) -> dict[str, str]:
    """`publishes` の宣言から topic → 型名の対応を作る。"""
    types: dict[str, str] = {}
    for decl in (base.get('drivers') or {}).values():
        for entry in (decl.get('publishes') or []):
            types[entry['topic']] = entry['type']
    return types


class DriverTelemetry:
    """宣言されたトピックを購読し、`telemetry` フレームを配る。"""

    def __init__(self, node: Node, emit: Callable[[dict[str, Any]], None],
                 *, base: dict[str, Any], robot: dict[str, Any], mode: str,
                 wall_clock) -> None:
        self.node = node
        self.emit = emit
        self._wall = wall_clock

        specs = load_specs(base, robot)
        derived = load_derived(base)
        self.store = TelemetryStore(specs, expected_drivers(base, mode), derived)
        self._setup_derived(derived)

        types = _topic_types(base)
        # トピック単位で 1 回だけ購読する。同じトピックから複数の field を
        # 引く宣言（model_cr2 の battery と電流）で購読が重複しないように。
        by_topic: dict[str, list] = {}
        for spec in specs:
            by_topic.setdefault(spec.topic, []).append(spec)

        for topic, topic_specs in by_topic.items():
            type_name = types.get(topic)
            if type_name is None:
                raise TelemetryError(
                    f'telemetry が参照する {topic} が publishes に宣言されていない。'
                    f'型が分からないので購読できない（cr2-base.yaml を直すこと）')
            node.create_subscription(
                _message_class(type_name), topic,
                lambda msg, s=topic_specs, t=topic: self._on_message(t, s, msg),
                TELEMETRY_QOS)

        node.get_logger().info(
            f'telemetry を {len(specs)} 件、{len(by_topic)} トピックから購読する')

    def _setup_derived(self, derived: list) -> None:
        """派生テレメトリの入力を購読する。

        宣言に `yaw_rate_vs_ndt` が無ければ何もしない。宣言を消したのに
        購読だけ残る、を作らない。
        """
        self.yaw_rate = None
        if not any(spec.name == DERIVED_YAW_RATE for spec in derived):
            return
        self.yaw_rate = YawRateVsNdt()
        node = self.node
        node.create_subscription(
            Imu, DERIVED_IMU_TOPIC, self._on_imu, TELEMETRY_QOS)
        node.create_subscription(
            PoseWithCovarianceStamped, DERIVED_NDT_TOPIC, self._on_ndt,
            TELEMETRY_QOS)

    def _on_imu(self, message: Imu) -> None:
        # **stamp は header から取る。** 受信時刻で積分すると、bag 再生や
        # 負荷で詰まったときに回転量がずれる。
        self.yaw_rate.observe_imu(
            _stamp(message), math.degrees(message.angular_velocity.z))

    def _on_ndt(self, message: PoseWithCovarianceStamped) -> None:
        q = message.pose.pose.orientation
        yaw = math.degrees(math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                                      1.0 - 2.0 * (q.y * q.y + q.z * q.z)))
        self.yaw_rate.observe_ndt(_stamp(message), yaw)
        # 評価は pose が来たときにしか進まないので、そのたびに書き戻す。
        self.store.set_value(
            DERIVED_YAW_RATE, self.yaw_rate.value, self._now())

    def _now(self) -> float:
        return self._wall.now().nanoseconds / 1e9

    def _on_message(self, topic: str, specs: list, message: Any) -> None:
        now = self._now()
        self.store.observe_topic(topic, now)
        for spec in specs:
            # __rate は到着そのものが値なので、ここでは何もしない。
            if spec.field == FIELD_RATE:
                continue
            self.store.set_value(spec.name, extract(message, spec.field), now)

    def frame(self) -> dict[str, Any]:
        return self.store.frame(self._now())

    def publish(self) -> None:
        """タイマーから呼ぶ。

        変化があったときだけ流す、はしない。値は常に動いているうえ、`age` と
        `__rate` は時間そのものが変化なので、結局毎回流れる。
        """
        self.emit(self.frame())


def _stamp(message: Any) -> float:
    return message.header.stamp.sec + message.header.stamp.nanosec / 1e9


def _message_class(type_name: str):
    """`whill_msgs/msg/ModelCr2State` のような文字列から型を解決する。"""
    from rosidl_runtime_py.utilities import get_message

    return get_message(type_name)
