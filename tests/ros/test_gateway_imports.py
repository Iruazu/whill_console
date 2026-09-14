"""gateway の各モジュールが import できることの smoke テスト。

telemetry.py と gateway.py は ROS の配線が主で、純粋関数のテストでは
覆えない。にもかかわらず、**未定義の名前や import 漏れは起動して初めて
分かる**（実際に `SENSOR_QOS` の未定義で gateway が起動時に落ちた）。

import が通ることと、購読しているトピック名の一覧が変わっていないことを
ここで見る。ROS のメッセージ型が無い環境では skip する。
"""

from __future__ import annotations

import pytest

rclpy = pytest.importorskip('rclpy', reason='ROS が無い環境')
pytest.importorskip('map_msgs', reason='map_msgs が無い環境')


def test_telemetry_module_imports():
    from whill_gateway import telemetry

    assert telemetry.SCAN_MAX_POINTS > 0
    assert telemetry.SENSOR_QOS is not None
    assert telemetry.LATCHED_QOS is not None


def test_gateway_module_imports():
    from whill_gateway import gateway

    assert gateway.STATUS_PERIOD_SEC > 0


def test_param_bridge_module_imports():
    from whill_gateway import param_bridge

    assert param_bridge.MOVING_HOLD_SEC > 0


def test_costmap_scopes_cover_local_and_global():
    from whill_gateway.telemetry import COSTMAP_SCOPES

    assert COSTMAP_SCOPES['local'] == '/local_costmap/costmap'
    assert COSTMAP_SCOPES['global'] == '/global_costmap/costmap'


def test_scan_is_a_default_stream():
    """俯瞰図の背景に要るので既定で流す。"""
    from whill_gateway import protocol

    assert protocol.MSG_SCAN in protocol.DEFAULT_STREAMS
    assert protocol.MSG_SCAN in protocol.STREAMS


def test_driver_topics_are_subscribed_best_effort():
    """ドライバが出すトピックは best-effort で購読していること（#52）。

    RELIABLE の購読は BEST_EFFORT の publisher から 1 通も受け取れない。しかも
    「繋がらない」ではなく**静かに何も届かない**。画像の購読が depth だけの指定
    （= RELIABLE）で、Phase 2 からカメラ画像が 1 枚も届いていなかった。

    best-effort の購読は reliable の publisher とも繋がるので、ドライバ側の
    設定に関わらず、こちらを best-effort に寄せれば取りこぼさない。
    宣言（cr2-base.yaml の publishes）を正にして、Telemetry が張る購読を突き合わせる。
    """
    import yaml
    from rclpy.qos import QoSProfile, QoSReliabilityPolicy

    from whill_gateway.telemetry import Telemetry
    from whill_params import registry as reg

    base = yaml.safe_load(
        (reg.config_root() / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
    driver_topics = {entry['topic']
                     for decl in base['drivers'].values()
                     for entry in decl.get('publishes') or []}

    class RecordingNode:
        def __init__(self):
            self.subscriptions = []

        def create_subscription(self, msg_type, topic, callback, qos):
            self.subscriptions.append((topic, qos))

        def get_clock(self):
            raise AssertionError('購読の配線だけを見るので時計は使わない')

    node = RecordingNode()
    Telemetry(node, lambda frame: None, costmap_hz=1.0, pose_hz=1.0,
              scan_hz=1.0, image_hz=1.0)

    checked = []
    for topic, qos in node.subscriptions:
        if topic not in driver_topics:
            continue
        checked.append(topic)
        assert isinstance(qos, QoSProfile), f'{topic}: depth だけの指定は RELIABLE になる'
        assert qos.reliability == QoSReliabilityPolicy.BEST_EFFORT, topic

    # 空振りで緑にしない。画像と LiDAR は必ず含まれているはず。
    assert '/camera/camera/color/image_raw/compressed' in checked
    assert '/scan' in checked


def test_web_knows_the_same_default_streams():
    """web は `subscribe` で一覧を置き換えるので、既定の一覧を web 側にも持つ（#52）。

    食い違うと、camera パネルを閉じたときに送り直す一覧から何かが抜け、
    **テレメトリや配車が黙って止まる**。
    """
    import re
    from pathlib import Path

    from whill_gateway import protocol

    source = (Path(__file__).resolve().parents[2] / 'web' / 'src' / 'lib' /
              'streams.ts').read_text('utf-8')
    block = source[source.index('DEFAULT_STREAMS = ['):source.index('] as const')]
    web = set(re.findall(r"'([a-z_]+)'", block))
    assert web == set(protocol.DEFAULT_STREAMS)
    assert protocol.MSG_IMAGE not in protocol.DEFAULT_STREAMS
