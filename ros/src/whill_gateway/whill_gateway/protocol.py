"""gateway ↔ Web のフレーム定義。

**このモジュールは websockets にも rclpy にも依存しない。** 純粋な辞書と
文字列だけを扱う。理由は 2 つ:

  1. CI（ROS コンテナ）で、WebSocket サーバを立てずに検証できる
  2. フレームの形が変わったことを、通信を動かさずにテストで捕まえられる

Web 側の対の実装は `web/src/lib/types.ts`。片方だけ変えないこと。

## 方向

  client → server : auth, subscribe, param_set, preset_apply, manual_vel,
                    heartbeat, estop, virtual_obstacles, replay_control,
                    dispatch_submit, dispatch_cancel
  server → client : hello, status, error, params, param_changed,
                    costmap, costmap_update, pose, path, tf, diagnostics,
                    image, replay, telemetry, dispatch_state,
                    dispatch_waypoints

## 認証

トークンは**最初のフレーム**で送る。クエリ文字列に載せないのは、URL が
ブラウザ履歴・プロキシログ・Referer に残るため。認証が済むまでサーバは
`hello` 以外の何も返さない。
"""

from __future__ import annotations

import json
from typing import Any

from whill_gateway import nav2_status

PROTOCOL_VERSION = 1
"""互換性のない変更をしたら上げる。`hello` に載せて Web 側が確認する。"""

# ---- client → server -------------------------------------------------------

MSG_AUTH = 'auth'
MSG_SUBSCRIBE = 'subscribe'
MSG_PARAM_SET = 'param_set'
MSG_PRESET_APPLY = 'preset_apply'
MSG_MANUAL_VEL = 'manual_vel'
MSG_HEARTBEAT = 'heartbeat'
MSG_ESTOP = 'estop'
MSG_VIRTUAL_OBSTACLES = 'virtual_obstacles'
MSG_PING = 'ping'
MSG_REPLAY_CONTROL = 'replay_control'
"""bag 再生の一時停止・再開・速度変更。**シークは含まない**（ADR-0004）。"""
MSG_DISPATCH_SUBMIT = 'dispatch_submit'
MSG_DISPATCH_CANCEL = 'dispatch_cancel'
"""配車の投入と取り消し。既存 `whill_dispatch` の `/dispatch/*` へ橋渡しする。

**手動操作（`/dispatch/teleop`）は橋渡ししない。** gateway の `manual_vel` +
ハートビートと役割が同じで、両方生かすと `/cmd_vel_teleop` に 2 経路から
書き込むことになり、どちらが止めているのか分からなくなる（設計原則 4）。
"""

CLIENT_MESSAGES = frozenset({
    MSG_AUTH, MSG_SUBSCRIBE, MSG_PARAM_SET, MSG_PRESET_APPLY,
    MSG_MANUAL_VEL, MSG_HEARTBEAT, MSG_ESTOP, MSG_VIRTUAL_OBSTACLES,
    MSG_PING, MSG_REPLAY_CONTROL,
    MSG_DISPATCH_SUBMIT, MSG_DISPATCH_CANCEL,
})

REPLAY_ACTIONS = frozenset({'pause', 'resume', 'set_rate'})
"""`replay_control` で受け付ける操作。

`seek` は入れない。入れないことを**明示的に書いておく**ため定数にしている。
理由は ADR-0004。
"""

MIN_REPLAY_RATE = 0.1
MAX_REPLAY_RATE = 10.0
"""再生速度の範囲。

下限より遅いと「止まっているのか極端に遅いのか」が `/clock` の停止判定
（1 秒）と区別できなくなる。上限より速いと gateway のレート制限より
bag のほうが速くなり、画面が飛び飛びになるだけで見る意味が無い。
"""

# ---- server → client -------------------------------------------------------

MSG_HELLO = 'hello'
MSG_STATUS = 'status'
MSG_ERROR = 'error'
MSG_PARAMS = 'params'
MSG_PARAM_CHANGED = 'param_changed'
MSG_COSTMAP = 'costmap'
MSG_COSTMAP_UPDATE = 'costmap_update'
MSG_POSE = 'pose'
MSG_PATH = 'path'
MSG_TF = 'tf'
MSG_DIAGNOSTICS = 'diagnostics'
MSG_SCAN = 'scan'
MSG_IMAGE = 'image'
MSG_PONG = 'pong'
MSG_OBSTACLES = 'obstacles'
"""server → client の仮想障害物の**現在の一覧**。

client → server の `virtual_obstacles` は「操作」で、こちらは「状態」。
同じ名前にすると、フレームを見たときにどちらの向きか分からなくなる。
"""
MSG_TELEMETRY = 'telemetry'
"""ドライバのテレメトリ（現在値と level）。

閾値の判定は gateway 側で済ませて `level` だけ渡す。判定を UI に置くと、
`whill doctor` や CLI から見たときに画面と違う答えが出る。
"""
MSG_DISPATCH_STATE = 'dispatch_state'
MSG_DISPATCH_WAYPOINTS = 'dispatch_waypoints'
"""配車の現在状態と、選べる地点の一覧。

`whill_dispatch` が居ないモード（replay）では流れない。空を流さないのは、
「配車していない」と「待機中」を UI が区別できなくなるため。
"""
MSG_REPLAY = 'replay'
"""bag 再生の位置と速度。replay モードでのみ流れる。

他のモードで空フレームを流さないこと。「再生していない」と「再生位置が
0 秒」を UI が区別できなくなる。
"""

SERVER_MESSAGES = frozenset({
    MSG_HELLO, MSG_STATUS, MSG_ERROR, MSG_PARAMS, MSG_PARAM_CHANGED,
    MSG_COSTMAP, MSG_COSTMAP_UPDATE, MSG_POSE, MSG_PATH, MSG_SCAN,
    MSG_TF, MSG_DIAGNOSTICS, MSG_IMAGE, MSG_PONG, MSG_OBSTACLES,
    MSG_REPLAY, MSG_TELEMETRY,
    MSG_DISPATCH_STATE, MSG_DISPATCH_WAYPOINTS,
})
"""server → client のフレーム一覧。

`STREAMS` がこの部分集合であることをテストで担保する。フレームを足したのに
こちらへ追加し忘れると、購読できないフレームを作ってしまう。
"""

# 認証前に送ってよいのはこれだけ。データフレームは 1 つも含めない。
PRE_AUTH_MESSAGES = frozenset({MSG_HELLO, MSG_ERROR})

# `subscribe` で選べるストリーム。ここに無い名前は拒否する（typo を
# 「黙って何も届かない」に変えないため）。
STREAMS = frozenset({
    MSG_STATUS, MSG_PARAMS, MSG_COSTMAP, MSG_POSE, MSG_PATH, MSG_SCAN,
    MSG_TF, MSG_DIAGNOSTICS, MSG_IMAGE, MSG_OBSTACLES, MSG_REPLAY,
    MSG_TELEMETRY, MSG_DISPATCH_STATE,
})

# フレーム種別 → それが属するストリーム。
#
# `costmap_update` を独立したストリームにしない。costmap を購読しているのに
# 部分更新が来ない構成を作れてしまうと、**地図が最初の 1 枚で固まる**
# （ADR-0002 の失敗そのもの）。実際、この対応表を入れる前は
# costmap_update が broadcast で捨てられていた。
_STREAM_OF = {
    MSG_COSTMAP_UPDATE: MSG_COSTMAP,
    # 地点一覧は配車パネルに出るもの。独立させると「一覧は来るのに状態が
    # 来ない」構成を作れてしまい、進捗が止まった配車パネルができる。
    MSG_DISPATCH_WAYPOINTS: MSG_DISPATCH_STATE,
    # 変更ログは params パネルに出るもの。params を購読していれば届く。
    # 独立させると「スライダーは出るのに変更履歴が来ない」構成を作れてしまう。
    MSG_PARAM_CHANGED: MSG_PARAMS,
}


def stream_of(kind: str) -> str:
    """そのフレームを受け取るのに必要な購読名を返す。"""
    return _STREAM_OF.get(kind, kind)

DEFAULT_STREAMS = frozenset({
    MSG_STATUS, MSG_PARAMS, MSG_COSTMAP, MSG_POSE, MSG_PATH, MSG_SCAN,
    # 俯瞰図に重ねて描くものなので既定で流す。置いたまま忘れられるのが
    # 一番まずいので、繋いだら必ず見えるようにする。
    MSG_OBSTACLES,
    # replay モードでしか流れないので、既定に入れておいて実害が無い。
    # 逆に外すと「再生しているのに位置が出ない」を購読設定で作れてしまう。
    MSG_REPLAY,
    # バッテリーと localization の健全性は、繋いだら必ず見えるべきもの。
    MSG_TELEMETRY,
    MSG_DISPATCH_STATE,
    # TF の途絶は Nav2 が止まる一番多い原因。パネルを開いたときだけ購読すると、
    # 開いていない端末では止まったことに気づけない（#51）。1 Hz・1 通約 1.1 KB。
    MSG_TF,
})
"""何も指定せずに繋いだときに流れるもの。画像は明示的に要求させる。"""


class ProtocolError(Exception):
    """受け取ったフレームが契約を満たしていない。"""


# ---- パース ----------------------------------------------------------------


def parse_client_message(raw: str | bytes) -> dict[str, Any]:
    """クライアントからの 1 フレームを検証して返す。

    ここを通らない入力を扱わないこと。WebSocket には任意の JSON を投げられる
    ので、UI 側の検査を信頼してはいけない。
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ProtocolError('UTF-8 として読めない') from exc

    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f'JSON として読めない: {exc.msg}') from exc

    if not isinstance(message, dict):
        raise ProtocolError('トップレベルがオブジェクトでない')

    kind = message.get('type')
    if not isinstance(kind, str):
        raise ProtocolError('type が無いか文字列でない')
    if kind not in CLIENT_MESSAGES:
        raise ProtocolError(f'未知の type: {kind}')

    return message


def require(message: dict[str, Any], field: str, types: type | tuple[type, ...]) -> Any:
    """必須フィールドを取り出す。無い/型違いは ProtocolError。"""
    if field not in message:
        raise ProtocolError(f'{message.get("type")}: {field} が無い')
    value = message[field]
    # bool は int の派生。数値を期待する場所に True が通らないようにする。
    if types is not bool and isinstance(value, bool) and not isinstance(types, tuple):
        if types in (int, float):
            raise ProtocolError(f'{message.get("type")}: {field} が bool')
    if not isinstance(value, types):
        raise ProtocolError(f'{message.get("type")}: {field} の型が不正')
    return value


def parse_subscribe(message: dict[str, Any]) -> frozenset[str]:
    """`subscribe` のストリーム一覧を検証する。"""
    streams = message.get('streams')
    if streams is None:
        return frozenset(DEFAULT_STREAMS)
    if not isinstance(streams, list):
        raise ProtocolError('subscribe: streams が配列でない')
    unknown = [s for s in streams if s not in STREAMS]
    if unknown:
        raise ProtocolError(f'subscribe: 未知のストリーム {unknown}')
    return frozenset(streams)


# ---- サーバ → クライアントのフレーム構築 -----------------------------------


def hello(*, robot_id: str, mode: str, authenticated: bool) -> dict[str, Any]:
    """接続直後に返す。認証前でも返してよい唯一の情報フレーム。

    個体名とモードは、認証に失敗したクライアントにも見える。LAN 限定の
    前提なのでこれ以上は隠さない。隠すと「繋がらないが理由が分からない」
    という切り分け不能な状態になる。
    """
    return {
        'type': MSG_HELLO,
        'protocol': PROTOCOL_VERSION,
        'robot_id': robot_id,
        'mode': mode,
        'authenticated': authenticated,
    }


def error(reason: str, *, fatal: bool = False) -> dict[str, Any]:
    """拒否の理由を必ず返す。黙って切らない。

    黙って切ると、クライアント側は「ネットワークが悪いのか、トークンが
    違うのか、値が範囲外なのか」を区別できない。
    """
    return {'type': MSG_ERROR, 'reason': reason, 'fatal': fatal}


def status(*, robot_id: str, mode: str, nav_state: str, estop: bool,
           clients: int, stamp: float, moving: bool = False,
           latency_ms: float | None = None,
           preset: str | None = None) -> dict[str, Any]:
    """上部帯に出すもの。1 秒に 1 回程度で十分。

    `nav_state` は `nav2_status.py` の 5 つ（#67）。真偽値の `nav_active` も
    残すが、**「active でない」理由は nav_state にしか無い**（起動していない /
    起動中 / 応答なし / activate されていない）。

    `moving` は「いま車体が動いているか」（`/cmd_vel` から判定）。Nav2 が
    active かどうかとは別もので、手動操作でも動く。UI は
    locked_while_moving のスライダーを無効化して見せるのに使う。
    """
    return {
        'type': MSG_STATUS,
        'robot_id': robot_id,
        'mode': mode,
        'nav_state': nav_state,
        'nav_active': nav_state == nav2_status.STATE_ACTIVE,
        'moving': moving,
        'estop': estop,
        'clients': clients,
        'stamp': stamp,
        'latency_ms': latency_ms,
        'preset': preset,
    }


def pong(token: Any) -> dict[str, Any]:
    """`ping` をそのまま打ち返す。

    遅延はクライアント側の往復で測る。`status` の `stamp` と受信時刻の差では
    測らない — ROS の時刻とブラウザの時計は同期していないし、replay モードでは
    `use_sim_time` で ROS 側が実時刻ですらない。**往復なら時計合わせが要らない。**
    """
    return {'type': MSG_PONG, 'token': token}


def encode(message: dict[str, Any]) -> str:
    """送信用の文字列にする。

    ensure_ascii=False なのは、パラメータの説明が日本語で、エスケープすると
    帯域が 3 倍近くになるため。allow_nan=False は、NaN を含む JSON が
    ブラウザの JSON.parse で落ちるのを送信側で止めるため（センサ由来の
    NaN が pose に混ざりうる）。
    """
    return json.dumps(message, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))


def safe_encode(message: dict[str, Any]) -> str:
    """NaN/Inf を null に潰してから encode する。

    テレメトリは 1 フレーム壊れても次が来る。NaN 1 個で送信例外を出して
    ストリームごと止めるより、その値だけ落として流し続けるほうがよい。
    """
    return encode(_scrub(message))


def _scrub(value: Any) -> Any:
    if isinstance(value, float):
        # NaN != NaN、Inf は比較で判定する（math を import しないで済ませる）
        if value != value or value in (float('inf'), float('-inf')):
            return None
        return value
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value
