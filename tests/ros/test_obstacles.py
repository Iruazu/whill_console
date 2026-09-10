"""仮想障害物の保持と検査のテスト。

`obstacles.py` は rclpy に依存しないので、ROS を立てずに全部検証できる。

見たいのは「WebSocket に投げられた任意の JSON で costmap を壊せないこと」。
NaN や巨大な半径が通ると、costmap の全域が塗られたり無限ループになる。
"""

from __future__ import annotations

import pytest

from whill_gateway.obstacles import (
    ALLOWED_FRAME,
    MAX_OBSTACLES,
    MAX_RADIUS_M,
    MIN_RADIUS_M,
    ObstacleError,
    ObstacleStore,
    apply_command,
    validate,
)


def circle(identifier: str = 'a', x: float = 1.0, y: float = 2.0,
           radius: float = 0.5) -> dict:
    return {'id': identifier, 'frame_id': ALLOWED_FRAME,
            'x': x, 'y': y, 'radius': radius}


# ---- 検査 ------------------------------------------------------------------


def test_valid_obstacle_is_normalized():
    assert validate(circle()) == {
        'id': 'a', 'frame_id': 'map', 'x': 1.0, 'y': 2.0, 'radius': 0.5}


def test_frame_id_defaults_to_map():
    item = validate({'id': 'a', 'x': 0.0, 'y': 0.0, 'radius': 0.5})
    assert item['frame_id'] == 'map'


def test_other_frames_are_rejected():
    """決め打ちにする。曖昧にすると「どの座標系で置いたのか分からない障害物」ができる。"""
    with pytest.raises(ObstacleError, match='frame_id'):
        validate({'id': 'a', 'frame_id': 'base_link', 'x': 0.0, 'y': 0.0, 'radius': 0.5})


@pytest.mark.parametrize('bad', [
    {'x': 0.0, 'y': 0.0, 'radius': 0.5},                       # id が無い
    {'id': '', 'x': 0.0, 'y': 0.0, 'radius': 0.5},             # id が空
    {'id': 5, 'x': 0.0, 'y': 0.0, 'radius': 0.5},              # id が文字列でない
])
def test_bad_id_is_rejected(bad):
    with pytest.raises(ObstacleError, match='id'):
        validate(bad)


def test_non_dict_is_rejected():
    with pytest.raises(ObstacleError, match='オブジェクトでない'):
        validate([1, 2, 3])


@pytest.mark.parametrize('field', ['x', 'y', 'radius'])
def test_nan_is_rejected(field):
    """NaN を通すと costmap の全域が塗られたり無限ループになる。"""
    raw = circle()
    raw[field] = float('nan')
    with pytest.raises(ObstacleError, match='有限でない'):
        validate(raw)


@pytest.mark.parametrize('field', ['x', 'y', 'radius'])
def test_infinity_is_rejected(field):
    raw = circle()
    raw[field] = float('inf')
    with pytest.raises(ObstacleError, match='有限でない'):
        validate(raw)


def test_bool_is_not_accepted_as_a_number():
    """bool は int の派生。数値の場所に True を通さない。"""
    raw = circle()
    raw['x'] = True
    with pytest.raises(ObstacleError, match='数値でない'):
        validate(raw)


def test_string_coordinates_are_rejected():
    raw = circle()
    raw['y'] = '3.0'
    with pytest.raises(ObstacleError, match='数値でない'):
        validate(raw)


def test_radius_below_the_floor_is_rejected():
    """costmap の解像度より小さい円は 1 セルも塗れず「置いたのに何も起きない」。"""
    with pytest.raises(ObstacleError, match='小さすぎる'):
        validate(circle(radius=MIN_RADIUS_M / 2))


def test_radius_above_the_ceiling_is_rejected():
    """巨大な円を置かれると costmap が埋まる。"""
    with pytest.raises(ObstacleError, match='上限'):
        validate(circle(radius=MAX_RADIUS_M + 0.1))


def test_negative_radius_is_rejected():
    with pytest.raises(ObstacleError, match='小さすぎる'):
        validate(circle(radius=-1.0))


# ---- 保持 ------------------------------------------------------------------


def test_replace_sets_the_whole_list():
    store = ObstacleStore()
    store.replace([circle('a'), circle('b')])
    assert [item['id'] for item in store.all()] == ['a', 'b']
    store.replace([circle('c')])
    assert [item['id'] for item in store.all()] == ['c']


def test_replace_rejects_duplicate_ids():
    """黙って潰すと「消したのに残る」ことになる。"""
    store = ObstacleStore()
    with pytest.raises(ObstacleError, match='重複'):
        store.replace([circle('a'), circle('a', x=9.0)])


def test_replace_rejects_non_list():
    store = ObstacleStore()
    with pytest.raises(ObstacleError, match='配列でない'):
        store.replace({'id': 'a'})


def test_replace_rejects_too_many():
    store = ObstacleStore()
    too_many = [circle(f'x{i}') for i in range(MAX_OBSTACLES + 1)]
    with pytest.raises(ObstacleError, match='上限'):
        store.replace(too_many)


def test_add_appends_and_overwrites_same_id():
    """同じ id は上書き。UI がドラッグで半径を変える操作を想定している。"""
    store = ObstacleStore()
    store.add(circle('a', radius=0.5))
    store.add(circle('a', radius=1.2))
    assert len(store) == 1
    assert store.all()[0]['radius'] == 1.2


def test_add_respects_the_limit():
    store = ObstacleStore()
    store.replace([circle(f'x{i}') for i in range(MAX_OBSTACLES)])
    with pytest.raises(ObstacleError, match='上限'):
        store.add(circle('extra'))


def test_add_of_existing_id_at_limit_is_allowed():
    """上限に達していても、既にあるものの更新は通す。"""
    store = ObstacleStore()
    store.replace([circle(f'x{i}') for i in range(MAX_OBSTACLES)])
    store.add(circle('x0', radius=1.0))
    assert len(store) == MAX_OBSTACLES


def test_remove_deletes_one():
    store = ObstacleStore()
    store.replace([circle('a'), circle('b')])
    store.remove('a')
    assert [item['id'] for item in store.all()] == ['b']


def test_removing_something_gone_is_not_an_error():
    """二重クリックや、他のクライアントが先に消した場合。"""
    store = ObstacleStore()
    store.replace([circle('a')])
    store.remove('nope')
    assert len(store) == 1


def test_remove_rejects_bad_id():
    store = ObstacleStore()
    with pytest.raises(ObstacleError, match='id'):
        store.remove(None)


def test_clear_empties():
    store = ObstacleStore()
    store.replace([circle('a'), circle('b')])
    store.clear()
    assert store.all() == []


def test_order_is_preserved():
    """並びが毎回変わると UI の一覧で追いにくい。"""
    store = ObstacleStore()
    store.replace([circle('c'), circle('a'), circle('b')])
    assert [item['id'] for item in store.all()] == ['c', 'a', 'b']


# ---- コマンド --------------------------------------------------------------


def test_apply_command_defaults_to_replace():
    store = ObstacleStore()
    apply_command(store, {'type': 'virtual_obstacles', 'obstacles': [circle('a')]})
    assert len(store) == 1


def test_apply_command_add_and_remove():
    store = ObstacleStore()
    apply_command(store, {'action': 'add', 'obstacle': circle('a')})
    apply_command(store, {'action': 'add', 'obstacle': circle('b')})
    assert len(store) == 2
    apply_command(store, {'action': 'remove', 'id': 'a'})
    assert [item['id'] for item in store.all()] == ['b']


def test_apply_command_clear():
    store = ObstacleStore()
    apply_command(store, {'action': 'add', 'obstacle': circle('a')})
    assert apply_command(store, {'action': 'clear'}) == []


def test_unknown_action_is_an_error():
    """黙って捨てると UI 側は「送ったのに効かない」理由を追えない。"""
    store = ObstacleStore()
    with pytest.raises(ObstacleError, match='未知の action'):
        apply_command(store, {'action': 'teleport'})


def test_empty_replace_clears_everything():
    """全消去の経路。costmap 層も空配列で消える。"""
    store = ObstacleStore()
    store.replace([circle('a')])
    assert apply_command(store, {'action': 'replace', 'obstacles': []}) == []


# ---- 契約 ------------------------------------------------------------------


def test_max_radius_matches_the_costmap_layer():
    """gateway と costmap 層で上限が食い違うと、通したのに丸められる。"""
    from whill_params.generate_nav2_params import (
        VIRTUAL_OBSTACLES_PLUGIN,
        _insert_virtual_obstacles,
        _ros_parameters,
    )

    params: dict = {'global_costmap': {'global_costmap': {'ros__parameters': {
        'plugins': ['inflation_layer'],
    }}}}
    _insert_virtual_obstacles(params, 'global_costmap')
    layer = _ros_parameters(params, 'global_costmap')[VIRTUAL_OBSTACLES_PLUGIN]
    assert layer['max_radius'] == MAX_RADIUS_M


def test_obstacles_is_a_server_frame_and_command_is_a_client_frame():
    """状態と操作で名前を分けていること。

    同じ名前だと、フレームを見たときにどちらの向きか分からなくなる。
    """
    from whill_gateway import protocol

    assert protocol.MSG_OBSTACLES in protocol.SERVER_MESSAGES
    assert protocol.MSG_VIRTUAL_OBSTACLES in protocol.CLIENT_MESSAGES
    assert protocol.MSG_OBSTACLES in protocol.DEFAULT_STREAMS
