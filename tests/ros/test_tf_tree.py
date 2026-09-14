"""tf パネルの要約（#51）。

`tf_tree.py` は rclpy に依存せず、時刻を引数で受け取るので決定的に検証できる。

見たいのは 3 つ:

  1. **TF が止まったら、親子関係が変わらなくても古さで分かる**
  2. **`/tf_static` の辺は止まっていても正常**
  3. **来ていない期待の辺・親が違う辺を「無い」と出す**（木に現れないので黙ると気づけない）
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from whill_gateway.tf_tree import (
    LEVEL_CRIT,
    LEVEL_OK,
    LEVEL_STATIC,
    LEVEL_UNJUDGED,
    LEVEL_WARN,
    DynamicEdgeSpec,
    TfTree,
    load_expectations,
)

CONFIG = Path(__file__).resolve().parents[2] / 'config' / 'robots'

MAP_ODOM = DynamicEdgeSpec('map', 'odom', warn_sec=1.0, crit_sec=3.0, source='localizer')
ODOM_BASE = DynamicEdgeSpec('odom', 'base_link', warn_sec=0.5, crit_sec=2.0, source='EKF')


def _edge(frame, child):
    return next(e for e in frame['edges'] if e['child'] == child)


def _feed(tree, parent, child, *, hz, start, end, static=False):
    t = start
    while t <= end + 1e-9:
        tree.observe(parent, child, static=static, wall_sec=t)
        t += 1.0 / hz


def _healthy_tree(until=10.0):
    tree = TfTree([MAP_ODOM, ODOM_BASE], [('base_link', 'imu_link')])
    tree.observe('base_link', 'imu_link', static=True, wall_sec=0.0)
    _feed(tree, 'map', 'odom', hz=10, start=0.0, end=until)
    _feed(tree, 'odom', 'base_link', hz=30, start=0.0, end=until)
    return tree


# ---- 途絶 -------------------------------------------------------------------


def test_healthy_tree_is_ok_with_measured_rates():
    frame = _healthy_tree().frame(10.01)
    assert _edge(frame, 'odom')['level'] == LEVEL_OK
    assert _edge(frame, 'base_link')['level'] == LEVEL_OK
    assert _edge(frame, 'odom')['rate_hz'] == pytest.approx(10, abs=0.5)
    assert _edge(frame, 'base_link')['rate_hz'] == pytest.approx(30, abs=1)
    assert frame['missing'] == []
    assert frame['roots'] == ['map']


@pytest.mark.parametrize('stopped_for, level', [
    (0.3, LEVEL_OK),
    (1.2, LEVEL_WARN),
    (3.5, LEVEL_CRIT),
])
def test_frozen_localizer_is_seen_by_age(stopped_for, level):
    """localizer が固まっても親子関係は変わらない。以前の要約はここで何も言わなかった。"""
    tree = _healthy_tree(until=10.0)
    # EKF は動き続ける
    _feed(tree, 'odom', 'base_link', hz=30, start=10.0, end=10.0 + stopped_for)
    frame = tree.frame(10.0 + stopped_for)
    map_odom = _edge(frame, 'odom')
    assert map_odom['level'] == level
    assert map_odom['age'] == pytest.approx(stopped_for, abs=0.02)
    assert _edge(frame, 'base_link')['level'] == LEVEL_OK
    # 親子関係は同じ
    assert frame['parents'] == {'odom': 'map', 'base_link': 'odom', 'imu_link': 'base_link'}


def test_stopped_edge_does_not_show_its_old_rate():
    """「停止中 10 Hz」は矛盾している。"""
    frame = _healthy_tree(until=10.0).frame(15.0)
    assert _edge(frame, 'odom')['rate_hz'] is None


def test_measured_worst_interval_stays_ok():
    """代表 bag の最大間隔（map->odom 0.192 s / odom->base_link 0.047 s）で鳴らない。"""
    tree = _healthy_tree(until=10.0)
    assert _edge(tree.frame(10.192), 'odom')['level'] == LEVEL_OK
    assert _edge(tree.frame(10.047), 'base_link')['level'] == LEVEL_OK


# ---- 静的な辺 ---------------------------------------------------------------


def test_static_edge_is_never_stale():
    tree = _healthy_tree()
    entry = _edge(tree.frame(10_000.0), 'imu_link')
    assert entry['level'] == LEVEL_STATIC
    assert entry['age'] is None


def test_edge_seen_once_on_tf_static_stays_static():
    tree = TfTree()
    tree.observe('base_link', 'laser', static=True, wall_sec=0.0)
    tree.observe('base_link', 'laser', static=False, wall_sec=1.0)
    assert _edge(tree.frame(100.0), 'laser')['level'] == LEVEL_STATIC


def test_unexpected_dynamic_edge_is_not_judged():
    """閾値を持たない辺に良し悪しを言わない。古さは出す。"""
    tree = TfTree([MAP_ODOM])
    tree.observe('base_link', 'wheel', static=False, wall_sec=0.0)
    entry = _edge(tree.frame(60.0), 'wheel')
    assert entry['level'] == LEVEL_UNJUDGED
    assert entry['age'] == pytest.approx(60.0)


# ---- 無い辺 -----------------------------------------------------------------


def test_missing_expected_edges_are_listed():
    tree = TfTree([MAP_ODOM, ODOM_BASE], [('base_link', 'imu_link')])
    _feed(tree, 'odom', 'base_link', hz=30, start=0.0, end=1.0)
    frame = tree.frame(1.0)
    missing = {(m['parent'], m['child'], m['kind']) for m in frame['missing']}
    assert missing == {('map', 'odom', 'dynamic'), ('base_link', 'imu_link', 'static')}
    # 木が分かれている（map が無いので odom が根）
    assert frame['roots'] == ['odom']


def test_wrong_parent_is_reported_with_the_actual_parent():
    """個体 yaml と実機（bag）の食い違い。cr2-01 の camera_link で実際に起きている。"""
    tree = TfTree([], [('velodyne', 'camera_link')])
    tree.observe('base_link', 'camera_link', static=True, wall_sec=0.0)
    (entry,) = tree.frame(0.0)['missing']
    assert entry['parent'] == 'velodyne'
    assert entry['actual_parent'] == 'base_link'


def test_nothing_received_still_reports_expectations():
    """TF が 1 本も来ていないときこそ「無い」を出す。"""
    tree = TfTree([MAP_ODOM, ODOM_BASE])
    assert tree.is_empty and tree.expects_anything
    assert len(tree.frame(0.0)['missing']) == 2


# ---- 宣言の読み取り ---------------------------------------------------------


def test_expectations_come_from_config():
    base = yaml.safe_load((CONFIG / 'cr2-base.yaml').read_text('utf-8'))
    robot = yaml.safe_load((CONFIG / 'cr2-01.yaml').read_text('utf-8'))
    dynamic, static = load_expectations(base, robot)
    by_child = {spec.child: spec for spec in dynamic}
    assert by_child['odom'].parent == 'map'
    assert by_child['base_link'].parent == 'odom'
    for spec in dynamic:
        assert 0 < spec.warn_sec < spec.crit_sec
    assert ('base_link', 'imu_link') in static


def test_frame_is_plain_json():
    import json

    json.dumps(_healthy_tree().frame(10.0))
