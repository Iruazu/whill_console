"""モックドライバの共通土台。

モックの目的は「実機がない状態で上位（Nav2 / gateway / Web UI）を開発し検証すること」。
物理を正確に再現することではない。したがって:

  - トピック名・型・レートは cr2-base.yaml の宣言と厳密に一致させる（ここが契約）
  - 中身は上位の分岐を一通り踏めるだけの妥当さがあればよい
  - 実機固有の癖（cold boot の SetPower 手順など）は「観測できる形」だけ模す

実機の値レンジがモックの想定と合っているかは実機検証待ち（docs/open-questions.md）。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

SENSOR_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
)
"""VLP-16 の実ドライバと同じ best-effort sensor-data QoS。

reliable にすると実機と挙動が変わり、costmap 側の QoS 不一致バグを
モックでは踏めなくなる。実機に合わせることが目的なのでここは変えない。
"""


def yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    """z 軸まわりの回転を (x, y, z, w) に。tf_transformations は入っていないので自前。"""
    half = yaw * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _config_root() -> Path:
    """whill_params の探索ロジックを再利用する。単一ソースを二重実装しない。"""
    from whill_params.registry import config_root
    return config_root()


def load_robot_config(robot_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(base, robot) の生辞書を返す。"""
    root = _config_root()
    with (root / 'robots' / 'cr2-base.yaml').open(encoding='utf-8') as handle:
        base = yaml.safe_load(handle)
    with (root / 'robots' / f'{robot_id}.yaml').open(encoding='utf-8') as handle:
        robot = yaml.safe_load(handle)
    return base, robot


def driver_declaration(base: dict[str, Any], driver: str) -> dict[str, Any]:
    """cr2-base.yaml の drivers.<name> を取り出す。未宣言は起動時に落とす。

    宣言に無いトピックを勝手に publish するモックを作らないための門番。
    Phase 0 の受け入れ判定はこの宣言を正としているので、ここが緩むと
    「トピックは出ているが宣言と食い違う」状態を検出できなくなる。
    """
    drivers = base.get('drivers') or {}
    if driver not in drivers:
        raise KeyError(f'cr2-base.yaml に drivers.{driver} の宣言が無い')
    return drivers[driver]


def declared_rate(declaration: dict[str, Any], topic: str, default: float = 10.0) -> float:
    for entry in declaration.get('publishes') or []:
        if entry.get('topic') == topic:
            return float(entry.get('rate_hz', default))
    return default


class MockDriverNode(Node):
    """全モックの基底。robot_id パラメータの解決と宣言の読み込みだけを持つ。"""

    driver_name: str = ''

    def __init__(self, node_name: str) -> None:
        super().__init__(node_name)
        self.declare_parameter('robot_id', 'cr2-01')
        self.robot_id = self.get_parameter('robot_id').value

        self.base, self.robot = load_robot_config(self.robot_id)
        self.declaration = driver_declaration(self.base, self.driver_name)
        self.hardware = (self.robot.get('hardware') or {}).get(self.driver_name, {}) or {}

        self.get_logger().info(
            f'{node_name}: robot={self.robot_id} '
            f'({self.robot.get("display_name", "?")}) — mock, 実機ではない')

    def rate_for(self, topic: str, default: float = 10.0) -> float:
        return declared_rate(self.declaration, topic, default)

    def period_for(self, topic: str, default: float = 10.0) -> float:
        return 1.0 / self.rate_for(topic, default)
