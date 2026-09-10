"""手動操作と E-stop の状態機械。

**時刻を引数で受け取り、内部で実時間を読まない。** 安全に関わる判定を
実時間に依存させると、テストが不安定になって「たまに落ちるから再実行」に
なり、結局誰も見なくなる。

## 設計原則 4 との関係

> 安全（Layer D、E-stop）は実機PC内で完結し、通信状態に依存しない。
> 手動操作はハートビート断（500 ms）で速度ゼロ。

この状態機械は **ROS のタイマーから駆動する**。asyncio 側のタスクにすると、
WebSocket の処理が詰まったときに一緒に止まる。Wi-Fi が切れて WebSocket が
黙るのは、まさにゼロを出さなければならない状況なので、そこで止まる実装は
意味を成さない。

## 出力先

gateway は twist_mux の **teleop スロット**（`/cmd_vel_teleop`、優先度 50）に
書く。既存 `whill_safety` の構成をそのまま使い、Layer D（優先度 100）を
迂回しない。つまり:

  - gateway のゼロは Nav2（優先度 10）に勝つ → 自律走行を止められる
  - Layer D のゼロは gateway に勝つ → 歩行者検知の停止を操作者が上書きできない

## ハートビートが切れたあとの振る舞い

ゼロを 1 回出して黙るのでは足りない。下流が最後の値を保持していると、
「ゼロを送ったのに動き続ける」ことになる。`zero_hold` の間ゼロを出し続け、
その後にスロットを手放す（twist_mux 側の 0.5 s タイムアウトが引き継ぐ）。

E-stop はこの限りではない。**解除するまでゼロを出し続ける。**
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_HEARTBEAT_TIMEOUT = 0.5
"""ハートビートが途切れてから速度ゼロにするまで（秒）。

registry の `whill_gateway.manual_heartbeat_timeout` が正。ここは既定値。
"""

DEFAULT_ZERO_HOLD = 2.0
"""ハートビート断のあと、ゼロを出し続ける時間（秒）。

twist_mux の入力タイムアウト 0.5 s より十分長く取る。短いと、gateway が
黙るのと twist_mux がスロットを落とすのが競合して、Nav2 の指令が
一瞬だけ通り抜ける隙ができる。
"""


@dataclass(frozen=True)
class Command:
    """このティックで gateway が出すべき指令。"""

    vx: float
    wz: float
    publish: bool
    """False なら何も publish しない（teleop スロットを手放す）。"""
    reason: str
    """なぜこの出力なのか。UI とログに出す。"""


IDLE = Command(0.0, 0.0, publish=False, reason='idle')


class ManualControl:
    """手動速度指令・ハートビート・E-stop をまとめた状態機械。

    使い方（すべて時刻を渡す）:

        control.command(vx, wz, now)   # Web から manual_vel が来た
        control.heartbeat(now)         # Web から heartbeat が来た
        control.engage_estop(now)      # E-stop
        control.release_estop(now)     # 解除（明示操作のみ）
        control.output(now)            # ROS タイマーから毎周期呼ぶ
    """

    def __init__(self, *, heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
                 zero_hold: float = DEFAULT_ZERO_HOLD) -> None:
        self.heartbeat_timeout = heartbeat_timeout
        self.zero_hold = zero_hold
        self._vx = 0.0
        self._wz = 0.0
        self._last_heartbeat: float | None = None
        self._engaged = False
        """手動操作のセッションが始まっているか。"""
        self._estop = False

    # ---- 入力 --------------------------------------------------------------

    def command(self, vx: float, wz: float, now: float) -> None:
        """手動速度指令。指令そのものがハートビートを兼ねる。

        別々にすると、指令だけ届いてハートビートが落ちたときに
        「動かしているのに停止扱い」になる。
        """
        self._vx = float(vx)
        self._wz = float(wz)
        self._engaged = True
        self._last_heartbeat = now

    def heartbeat(self, now: float) -> None:
        """生存通知だけ。指令値は変えない。

        セッションを開始はしない。手動操作を始めていないクライアントの
        ハートビートで teleop スロットを掴むと、Nav2 の指令を邪魔する。
        """
        if self._engaged:
            self._last_heartbeat = now

    def release(self) -> None:
        """手動操作を明示的に終える。次のティックからスロットを手放す。"""
        self._engaged = False
        self._vx = 0.0
        self._wz = 0.0
        self._last_heartbeat = None

    def engage_estop(self, now: float) -> None:
        # 手動の指令値も落とす。解除した瞬間に古い速度が復活しないように。
        self._vx = 0.0
        self._wz = 0.0
        self._estop = True
        del now

    def release_estop(self) -> None:
        """解除は明示操作のみ。時間で自動解除しない。"""
        self._estop = False
        # 解除後に手動操作が勝手に再開しないよう、セッションも終わらせる。
        self._engaged = False
        self._last_heartbeat = None

    # ---- 参照 --------------------------------------------------------------

    @property
    def estop(self) -> bool:
        return self._estop

    @property
    def engaged(self) -> bool:
        return self._engaged

    def stale(self, now: float) -> bool:
        if self._last_heartbeat is None:
            return True
        return (now - self._last_heartbeat) > self.heartbeat_timeout

    # ---- 出力 --------------------------------------------------------------

    def output(self, now: float) -> Command:
        """このティックで publish すべき指令。

        ROS のタイマーから毎周期呼ぶ。呼ばれ続けることが前提の設計で、
        呼ばれなくなったら安全側に倒れない — だからこそ asyncio ではなく
        ROS のタイマーに置く。
        """
        if self._estop:
            # 解除するまでゼロを出し続ける。Nav2（優先度 10）に勝つので
            # 自律走行も止まる。
            return Command(0.0, 0.0, publish=True, reason='estop')

        if not self._engaged:
            return IDLE

        if not self.stale(now):
            return Command(self._vx, self._wz, publish=True, reason='manual')

        # ハートビート断。ゼロを出し続ける。1 回出して黙ると、下流が
        # 最後の値を保持している場合に動き続ける。
        assert self._last_heartbeat is not None
        since_loss = now - self._last_heartbeat - self.heartbeat_timeout
        if since_loss <= self.zero_hold:
            return Command(0.0, 0.0, publish=True, reason='heartbeat_lost')

        # 十分ゼロを出したのでスロットを手放す。ここから先は twist_mux の
        # 入力タイムアウトが効き、Nav2 の指令が通るようになる。
        self._engaged = False
        self._last_heartbeat = None
        return IDLE
