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
