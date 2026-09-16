"""Nav2 が動いているかの判定（#67）。

**rclpy に依存しない。** サービスの応答と時刻を渡すだけなので、Nav2 を立てずに
検証できる。実際に問い合わせるのは `gateway.py`。

## なぜ真偽値では足りないか

上部帯は `nav_active` という真偽値 1 つで「active / inactive」と出していた
（しかも値は固定で、常に inactive だった）。真偽値だと次の 3 つが同じ絵になる:

- Nav2 を**起動していない**モード（replay は Nav2 を上げない — ADR-0004）
- 起動しているはずなのに**応答が無い**（本当に困る状態）
- 起動直後で**まだ上がりきっていない**

「いつも赤い表示」は、そのうち誰も見なくなる。区別して出す。

## 何をもって active とするか

`nav2_bringup` の `navigation_launch.py` が立てる `lifecycle_manager_navigation`
の `is_active` サービス（`std_srvs/srv/Trigger`）を見る。**Nav2 一式が上がって
いるか**を 1 つで答えるので、上部帯のバッジ 1 個と粒度が合う。

個別ノード（`bt_navigator` など）の lifecycle を見る案は採らない。どれが落ちた
かまで出せるが、バッジ 1 個には情報が多すぎる。どのノードが落ちたかは
drivers パネルと `whill doctor` の領分。

「goal を実行中か」とも別。それは配車パネルが既に出している。
"""

from __future__ import annotations

STATE_NOT_STARTED = 'not_started'
"""このモードは Nav2 を起動しない（replay）。異常ではない。"""

STATE_STARTING = 'starting'
"""起動直後で、まだ応答が無い。"""

STATE_ACTIVE = 'active'
STATE_INACTIVE = 'inactive'
"""lifecycle manager は居るが、Nav2 が activate されていない。"""

STATE_DOWN = 'down'
"""起動しているはずなのに応答が無い。**これが一番困る状態。**"""

STARTUP_GRACE_SEC = 20.0
"""起動中とみなす時間。

Nav2 一式（mock 構成）が上がるまで実測で 5〜10 秒かかる。短くすると、
正常な起動のたびに「応答なし」が赤く出て、本物の故障と区別が付かなくなる。
"""

STALE_AFTER_SEC = 5.0
"""最後に答えが返ってから、これを過ぎたら応答なしとみなす。

問い合わせは status と同じ 1 Hz なので、3 回連続で取りこぼしたら赤くする。
"""


class Nav2Watch:
    """問い合わせの結果を受け、いまの状態を答える。時刻は全部引数で受け取る。"""

    def __init__(self, *, started: bool, started_at: float,
                 grace_sec: float = STARTUP_GRACE_SEC,
                 stale_after_sec: float = STALE_AFTER_SEC) -> None:
        self._started = started
        self._started_at = started_at
        self._grace = grace_sec
        self._stale_after = stale_after_sec
        self._last_reply: float | None = None
        self._active = False

    @property
    def started(self) -> bool:
        return self._started

    def observe(self, *, active: bool, wall_sec: float) -> None:
        """`is_active` から答えが返ったとき。"""
        self._active = active
        self._last_reply = wall_sec

    def state(self, wall_sec: float) -> str:
        if not self._started:
            # 起動していないものを「応答なし」と出さない。replay で毎回赤くなる。
            return STATE_NOT_STARTED
        if self._last_reply is None:
            return STATE_STARTING if wall_sec - self._started_at < self._grace \
                else STATE_DOWN
        if wall_sec - self._last_reply >= self._stale_after:
            # 一度は答えたのに黙った。落ちたか、繋がらなくなった。
            return STATE_DOWN
        return STATE_ACTIVE if self._active else STATE_INACTIVE


def starts_nav2(base: dict, mode: str) -> bool:
    """このモードが Nav2 を起動するか。`cr2-base.yaml` の `modes.*.include_stack` が正。"""
    mode_decl = (base.get('modes') or {}).get(mode) or {}
    return bool(mode_decl.get('include_stack', True))
