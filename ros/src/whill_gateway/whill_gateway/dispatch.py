"""既存 `whill_dispatch` の `/dispatch/*` を gateway の口に繋ぐ。

## なぜ橋渡しするのか

既存の配車 UI はブラウザから **rosbridge に直接** 繋いでいる
（`whill_dispatch/web/vendor/roslib.min.js`）。設計原則 1 に反する:

> ROS は実機PC内に閉じる。ROS への口は `whill_gateway` の WebSocket 1 本と ssh のみ。

`whill_dispatch` の**ノードは触らない**（`CLAUDE.md`: 既存スタックは参照と
include の対象であって編集対象ではない）。境界が既に素直に切れているので、
gateway がその境界の内側に立てば済む。

    Web -> ROS  /dispatch/submit     (String)  JSON
    Web -> ROS  /dispatch/cancel     (Trigger)
    ROS -> Web  /dispatch/state      (String, 5 Hz)
    ROS -> Web  /dispatch/waypoints  (String, 1 Hz)

## 何を捨てるか

**`teleop_active` と `/dispatch/teleop` は橋渡ししない。** gateway の
`manual_vel` + ハートビートと役割が同じで、両方生かすと `/cmd_vel_teleop` に
2 経路から書き込むことになり、**どちらが止めているのか分からなくなる**
（設計原則 4 に真正面から反する）。手動操作は gateway 側に一本化する。

**`battery` と `pose` も落とす。** どちらも gateway が別の口
（telemetry, pose）で既に配っている。同じ数字を 2 経路で配ると、食い違ったとき
どちらが正しいか分からない。**1 つの数字には 1 つの出どころ。**

**`aligned` / `fitness` は残す。** これは「配車してよい状態か」を判断する材料で、
配車の操作と同じ場所に出ているべきもの（既存 UI も submit ボタンの隣に
出している）。telemetry 側で重複させないこと。

## 再送であって latched ではない

`whill_dispatch` は state を 5 Hz、waypoints を 1 Hz で**再送している**
（roslibjs が volatile で購読するため latched にできなかった）。gateway は
最新を保持して接続時に配る。保持しないと、繋いだ直後の 1 秒間だけ
地点一覧が空の配車パネルが出る。
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any

from rclpy.node import Node

from std_msgs.msg import String
from std_srvs.srv import Trigger

from whill_gateway import protocol

STATE_TOPIC = '/dispatch/state'
WAYPOINTS_TOPIC = '/dispatch/waypoints'
SUBMIT_TOPIC = '/dispatch/submit'
CANCEL_SERVICE = '/dispatch/cancel'

TERMINAL_PHASES = frozenset({'SUCCEEDED', 'ABORTED', 'CANCELED'})
"""終わり方。`whill_dispatch` は次の job が始まるまでこれを残す。

こちらでも消さない。一瞬で消すと、短い job の結末を見逃す。
"""

_STATE_KEYS = ('job_id', 'phase', 'waypoint', 'progress', 'queue_len',
               'aligned', 'fitness')
"""Web へ渡す state のキー。

`pose` / `battery` / `teleop_active` は**意図的に外している**（モジュール
docstring 参照）。ここに足すときは、その数字を配る口が他に無いことを
確かめること。
"""


class DispatchError(Exception):
    """クライアントから来た配車指令が契約を満たしていない。"""


def parse_state(payload: str) -> dict[str, Any] | None:
    """`/dispatch/state` の JSON を Web へ渡す形にする。

    **gateway でパースする。** 文字列のまま渡すと web 側が二重パースになり、
    命名変換が `frames.ts` の 1 か所に閉じなくなる。

    壊れた JSON は None。既存ノードが出すものなので普段は起きないが、
    起きたときにテレメトリごと止めない。
    """
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    frame: dict[str, Any] = {'type': protocol.MSG_DISPATCH_STATE}
    for key in _STATE_KEYS:
        frame[key] = raw.get(key)
    return frame


def parse_waypoints(payload: str) -> dict[str, Any] | None:
    """`/dispatch/waypoints` の JSON を Web へ渡す形にする。"""
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    points = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            continue
        points.append({
            'name': item['name'],
            # label が無ければ name で代用する。空文字のボタンを出さない。
            'label': item.get('label') or item['name'],
            'x': _number(item.get('x')),
            'y': _number(item.get('y')),
            'yaw': _number(item.get('yaw')),
        })
    return {'type': protocol.MSG_DISPATCH_WAYPOINTS, 'waypoints': points}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def build_submit(message: dict[str, Any], known: set[str]) -> str:
    """クライアントの `dispatch_submit` を `/dispatch/submit` の JSON にする。

    WebSocket には任意の JSON を投げられるので、UI 側の検査を信頼しない。
    既存ノードも不正な submit を落とす作りだが、**そちらは黙って warn ログに
    書くだけ**なので、UI からは「押したのに何も起きない」に見える。ここで
    弾いて理由を返す。
    """
    if 'waypoint' in message:
        name = message['waypoint']
        if not isinstance(name, str) or not name:
            raise DispatchError('waypoint が文字列でない')
        if known and name not in known:
            # 一覧をまだ受け取っていない (known が空) ときは素通しする。
            # 起動直後に「知らない地点」で拒否すると、原因が分かりにくい。
            raise DispatchError(
                f'知らない地点: {name}（選べるのは {sorted(known)}）')
        return json.dumps({'waypoint': name, 'type': 'pickup'})

    point = message.get('point')
    if not isinstance(point, dict):
        raise DispatchError('waypoint も point も無い')
    x, y = _number(point.get('x')), _number(point.get('y'))
    if x is None or y is None:
        # NaN をそのまま流すと、既存ノード側で無効な goal になる。
        raise DispatchError('point の x / y が有限な数値でない')
    yaw = _number(point.get('yaw')) or 0.0
    return json.dumps({'point': {'x': x, 'y': y, 'yaw': yaw}, 'type': 'pickup'})


class DispatchBridge:
    """`/dispatch/*` の購読・publish とサービス呼び出し。"""

    def __init__(self, node: Node, emit: Callable[[dict[str, Any]], None]) -> None:
        self.node = node
        self.emit = emit
        self._state: dict[str, Any] | None = None
        self._waypoints: dict[str, Any] | None = None

        node.create_subscription(String, STATE_TOPIC, self._on_state, 10)
        node.create_subscription(String, WAYPOINTS_TOPIC, self._on_waypoints, 10)
        self._submit_pub = node.create_publisher(String, SUBMIT_TOPIC, 10)
        self._cancel = node.create_client(Trigger, CANCEL_SERVICE)

    # ---- ROS → Web ---------------------------------------------------------

    def _on_state(self, msg: String) -> None:
        frame = parse_state(msg.data)
        if frame is None:
            return
        # 中身が変わったときだけ流す。5 Hz で同じ内容を配ると、待機中の
        # 配車パネルが WebSocket の大半を占める。
        if frame == self._state:
            return
        self._state = frame
        self.emit(frame)

    def _on_waypoints(self, msg: String) -> None:
        frame = parse_waypoints(msg.data)
        if frame is None or frame == self._waypoints:
            return
        self._waypoints = frame
        self.emit(frame)

    def snapshot(self) -> list[dict[str, Any]]:
        """繋いだ直後に配る。

        既存ノードは latched ではなく再送なので、これが無いと最初の 1 秒は
        地点一覧が空の配車パネルが出る。
        """
        return [f for f in (self._waypoints, self._state) if f is not None]

    @property
    def known_waypoints(self) -> set[str]:
        if self._waypoints is None:
            return set()
        return {w['name'] for w in self._waypoints['waypoints']}

    # ---- Web → ROS ---------------------------------------------------------

    def submit(self, message: dict[str, Any]) -> None:
        payload = build_submit(message, self.known_waypoints)
        self._submit_pub.publish(String(data=payload))
        self.node.get_logger().info(f'配車を投入した: {payload}')

    def cancel(self) -> None:
        """走行中の job を取り消す。

        **応答は待たない。** `wait_for_service` は executor と競合して購読
        コールバックごと止める（K9）。効いたかどうかは次の `dispatch_state` の
        `phase` が CANCELED になることで分かる。
        """
        if not self._cancel.service_is_ready():
            raise DispatchError(
                f'{CANCEL_SERVICE} に届かない（dispatch_node が起動していない）')
        self._cancel.call_async(Trigger.Request())
        self.node.get_logger().info('配車の取り消しを送った')
