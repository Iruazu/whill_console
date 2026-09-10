"""配車の橋渡しのテスト。

`dispatch.py` のパース・検査は rclpy に依存しないので、ROS を立てずに検証できる。

見たいのは 2 つ:

  1. **Web へ渡さないと決めたキーが漏れないこと。** `pose` と `battery` は
     gateway が別の口で配っており、2 経路で配ると食い違ったときにどちらが
     正しいか分からない。`teleop_active` は手動操作の二重化そのもの
  2. **不正な submit が「押したのに何も起きない」にならないこと。** 既存ノードは
     warn ログに書いて落とすだけなので、UI からは理由が見えない
"""

from __future__ import annotations

import json

import pytest

from whill_gateway.dispatch import (
    DispatchError,
    build_submit,
    parse_state,
    parse_waypoints,
)

STATE = {
    'job_id': 3, 'phase': 'ACTIVE', 'waypoint': 'east', 'progress': 0.42,
    'queue_len': 1, 'pose': {'x': 1.0, 'y': 2.0, 'yaw': 0.3},
    'aligned': True, 'fitness': 0.31, 'battery': 87, 'teleop_active': False,
}


# ---- state ------------------------------------------------------------------


def test_state_keeps_what_the_dispatch_panel_needs():
    frame = parse_state(json.dumps(STATE))
    assert frame == {
        'type': 'dispatch_state',
        'job_id': 3, 'phase': 'ACTIVE', 'waypoint': 'east',
        'progress': 0.42, 'queue_len': 1, 'aligned': True, 'fitness': 0.31,
    }


@pytest.mark.parametrize('dropped', ['pose', 'battery', 'teleop_active'])
def test_state_drops_what_another_stream_owns(dropped):
    """1 つの数字には 1 つの出どころ。

    pose と battery は gateway が別の口で配っている。teleop_active は
    手動操作の二重化（設計原則 4）。
    """
    assert dropped not in parse_state(json.dumps(STATE))


def test_missing_keys_become_none_not_zero():
    """まだ何も走っていない状態を「進捗 0 の job がある」に見せない。"""
    frame = parse_state(json.dumps({'phase': 'IDLE'}))
    assert frame['job_id'] is None
    assert frame['progress'] is None
    assert frame['phase'] == 'IDLE'


def test_broken_json_is_dropped_not_raised():
    """既存ノードが出すものなので普段は起きないが、起きても他を止めない。"""
    assert parse_state('{not json') is None
    assert parse_state('[1, 2]') is None


# ---- waypoints --------------------------------------------------------------


def test_waypoints_are_normalized():
    frame = parse_waypoints(json.dumps([
        {'name': 'east', 'label': '東端', 'x': 7.0, 'y': 0.0, 'yaw': 0.0},
    ]))
    assert frame == {
        'type': 'dispatch_waypoints',
        'waypoints': [{'name': 'east', 'label': '東端',
                       'x': 7.0, 'y': 0.0, 'yaw': 0.0}],
    }


def test_label_falls_back_to_name():
    """空文字のボタンを出さない。"""
    frame = parse_waypoints(json.dumps([{'name': 'east', 'x': 1, 'y': 2}]))
    assert frame['waypoints'][0]['label'] == 'east'


def test_waypoints_without_a_name_are_skipped():
    frame = parse_waypoints(json.dumps([{'label': '名無し'}, {'name': 'ok'}]))
    assert [w['name'] for w in frame['waypoints']] == ['ok']


def test_non_finite_coordinates_become_none():
    """NaN を渡すとブラウザの JSON.parse が落ちる。"""
    frame = parse_waypoints('[{"name": "a", "x": NaN, "y": 1.0}]')
    assert frame['waypoints'][0]['x'] is None
    assert frame['waypoints'][0]['y'] == 1.0


def test_broken_waypoints_are_dropped():
    assert parse_waypoints('{"not": "a list"}') is None


# ---- submit -----------------------------------------------------------------


KNOWN = {'west', 'center', 'east'}


def test_submit_by_waypoint_name():
    assert json.loads(build_submit({'waypoint': 'east'}, KNOWN)) == {
        'waypoint': 'east', 'type': 'pickup'}


def test_unknown_waypoint_is_rejected_with_the_choices():
    """既存ノードは warn ログに書いて落とすだけ。UI からは理由が見えない。"""
    with pytest.raises(DispatchError, match='知らない地点'):
        build_submit({'waypoint': 'nope'}, KNOWN)


def test_unknown_waypoint_passes_before_the_list_arrives():
    """起動直後に「知らない地点」で拒否すると原因が分かりにくい。"""
    assert json.loads(build_submit({'waypoint': 'east'}, set()))['waypoint'] == 'east'


def test_submit_by_point():
    payload = json.loads(build_submit({'point': {'x': 1.5, 'y': -2.0}}, KNOWN))
    assert payload == {'point': {'x': 1.5, 'y': -2.0, 'yaw': 0.0},
                       'type': 'pickup'}


def test_point_yaw_is_optional():
    payload = json.loads(build_submit({'point': {'x': 0, 'y': 0, 'yaw': 1.2}}, KNOWN))
    assert payload['point']['yaw'] == 1.2


@pytest.mark.parametrize('point', [
    {'x': float('nan'), 'y': 0.0},
    {'x': 0.0, 'y': float('inf')},
    {'x': '1', 'y': 0.0},
    {'x': True, 'y': 0.0},
    {'y': 0.0},
])
def test_bad_points_are_rejected(point):
    with pytest.raises(DispatchError, match='有限な数値でない'):
        build_submit({'point': point}, KNOWN)


def test_submit_without_a_target_is_rejected():
    with pytest.raises(DispatchError, match='waypoint も point も無い'):
        build_submit({}, KNOWN)


def test_empty_waypoint_name_is_rejected():
    with pytest.raises(DispatchError, match='文字列でない'):
        build_submit({'waypoint': ''}, KNOWN)


# ---- 契約 -------------------------------------------------------------------


def test_state_and_waypoints_share_one_stream():
    """独立させると「一覧は来るのに状態が来ない」構成を作れてしまう。"""
    from whill_gateway import protocol

    assert protocol.stream_of(protocol.MSG_DISPATCH_WAYPOINTS) == \
        protocol.MSG_DISPATCH_STATE
    assert protocol.MSG_DISPATCH_STATE in protocol.STREAMS
    assert protocol.MSG_DISPATCH_WAYPOINTS not in protocol.STREAMS


def test_submit_and_cancel_are_client_frames():
    from whill_gateway import protocol

    assert protocol.MSG_DISPATCH_SUBMIT in protocol.CLIENT_MESSAGES
    assert protocol.MSG_DISPATCH_CANCEL in protocol.CLIENT_MESSAGES
    assert protocol.MSG_DISPATCH_STATE in protocol.SERVER_MESSAGES


def test_teleop_is_not_bridged():
    """手動操作は gateway の manual_vel に一本化する（設計原則 4）。

    `/cmd_vel_teleop` に 2 経路から書き込むと、どちらが止めているのか
    分からなくなる。
    """
    from whill_gateway import dispatch, protocol

    assert 'teleop' not in str(protocol.CLIENT_MESSAGES)
    assert not hasattr(dispatch, 'TELEOP_TOPIC')
    assert 'teleop' not in dispatch._STATE_KEYS


FOOTPRINT_M = 0.4
"""車体まわりに要る余裕。WHILL CR の全幅は約 0.6 m。

壁ぎりぎりの地点は inflation layer で到達不能になり、「地点は地図の中に
あるのに ABORTED」という一番分かりにくい失敗になる。"""


def test_mock_waypoints_are_inside_the_mock_map():
    """実機の地点をそのまま mock で使うと全部 ABORTED になる。

    「配線が壊れているのか地点が地図の外なのか」が区別できない状態を作らない。

    生成物（`mock_corridor.yaml`）ではなく生成器の定数を見る。生成物は
    gitignore されていて CI には無い — **無いから skip では、この検査が
    CI で一度も走らないことになる。**
    """
    import sys
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'scripts'))
    try:
        from make_mock_map import free_bounds
    finally:
        sys.path.pop(0)

    x_min, x_max, y_min, y_max = free_bounds()
    points = yaml.safe_load(
        (root / 'ros' / 'src' / 'whill_bringup' / 'config'
         / 'mock_waypoints.yaml').read_text('utf-8'))

    assert points['frame_id'] == 'map'
    assert points['waypoints'], '地点が 1 つも無い'
    for wp in points['waypoints']:
        # 壁ぎりぎりだと inflation で到達不能になる。車体半径ぶん内側を要求する。
        assert x_min + FOOTPRINT_M < wp['x'] < x_max - FOOTPRINT_M, \
            f'{wp["name"]} が廊下の外か壁に近すぎる'
        assert y_min + FOOTPRINT_M < wp['y'] < y_max - FOOTPRINT_M, \
            f'{wp["name"]} が廊下の外か壁に近すぎる'
