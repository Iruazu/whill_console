"""bag 再生の進捗。

**rclpy に依存しない。** `/clock` の値と実時間を渡すだけなので、ROS を立てずに
検証できる。

## なぜ要るか

再生中に「いま bag のどこを見ているか」が分からないと、止まっている絵が
「再生が終わった」のか「その時刻に車体が止まっていた」のか区別できない。
2026-07-31 の走行には実際に停止している区間があるので、これは実害のある
曖昧さ。

## 再生速度は「観測値」を出す

`set_rate` で指令した値ではなく、`/clock` の進みと実時間の比を出す。
指令が 1.0 でも実機PC が重ければ実際は 0.7 倍しか進まない。**指令値を
出すと「速い/遅い」の判断を誤る。**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STALL_AFTER_SEC = 1.0
"""`/clock` がこの時間（実時間）進まなければ「停止中」とみなす。

一時停止と再生終了の両方がこれで拾える。短すぎると 1x 再生の揺らぎで
点滅するので、1 秒は取る。
"""

RATE_WINDOW_SEC = 2.0
"""再生速度を平均する窓（実時間）。

短いと数字が暴れて読めない。長いと一時停止への追随が遅れる。
"""


@dataclass(frozen=True)
class BagInfo:
    """bag の metadata.yaml から読んだもの。"""

    path: str
    start_sec: float
    duration_sec: float


def read_bag_info(bag_path: str) -> BagInfo | None:
    """`metadata.yaml` から開始時刻と長さを読む。

    読めなければ None。**進捗が出ないだけで再生自体は成り立つ**ので、
    ここで落とさない。
    """
    import os

    import yaml

    metadata = os.path.join(bag_path, 'metadata.yaml')
    if not os.path.isfile(metadata):
        return None
    try:
        with open(metadata, encoding='utf-8') as handle:
            data = yaml.safe_load(handle)
        info = data['rosbag2_bagfile_information']
        start_ns = info['starting_time']['nanoseconds_since_epoch']
        duration_ns = info['duration']['nanoseconds']
    except (KeyError, TypeError, ValueError, OSError):
        return None
    return BagInfo(path=bag_path,
                   start_sec=start_ns / 1e9,
                   duration_sec=duration_ns / 1e9)


class ReplayProgress:
    """`/clock` の観測から進捗と再生速度を出す。

    時刻はすべて引数で受け取る。実時間を内部で読まないのでテストが決定的。
    """

    def __init__(self, info: BagInfo | None) -> None:
        self.info = info
        self._clock: float | None = None
        self._clock_at: float | None = None
        """最後に `/clock` が**進んだ**ときの実時間。同じ値の再送では更新しない。"""
        self._window: list[tuple[float, float]] = []
        """(実時間, sim 時刻) の履歴。速度の平均に使う。"""

    def observe(self, clock_sec: float, wall_sec: float) -> None:
        if self._clock is not None and clock_sec <= self._clock:
            # 進んでいない。停止判定のために時刻を更新しない。
            return
        self._clock = clock_sec
        self._clock_at = wall_sec
        self._window.append((wall_sec, clock_sec))
        cutoff = wall_sec - RATE_WINDOW_SEC
        self._window = [(w, c) for w, c in self._window if w >= cutoff]

    def rate(self, wall_sec: float) -> float | None:
        """観測した再生速度。窓に 2 点以上ないと出さない。

        **止まっているあいだは出さない。** 窓は `/clock` が来たときにしか
        更新されないので、素直に計算すると一時停止した瞬間の速度が
        そのまま残る。「停止中 1.0x」という矛盾した表示になっていた。
        """
        if not self.playing(wall_sec):
            return None
        if len(self._window) < 2:
            return None
        (w0, c0), (w1, c1) = self._window[0], self._window[-1]
        if w1 <= w0:
            return None
        return (c1 - c0) / (w1 - w0)

    def playing(self, wall_sec: float) -> bool:
        if self._clock_at is None:
            return False
        return (wall_sec - self._clock_at) < STALL_AFTER_SEC

    def elapsed(self) -> float | None:
        if self.info is None or self._clock is None:
            return None
        return max(0.0, self._clock - self.info.start_sec)

    def frame(self, wall_sec: float) -> dict[str, Any]:
        """UI へ渡す形。

        `total` が None なら metadata が読めなかったということ。**進捗バーを
        0% で描かせない**ため、UI が判断できるよう明示的に None を返す。
        """
        elapsed = self.elapsed()
        total = self.info.duration_sec if self.info else None
        rate = self.rate(wall_sec)
        playing = self.playing(wall_sec)
        return {
            'type': 'replay',
            'bag': self.info.path if self.info else None,
            'elapsed': round(elapsed, 2) if elapsed is not None else None,
            'total': round(total, 2) if total is not None else None,
            'rate': round(rate, 2) if rate is not None else None,
            'playing': playing,
            # 終わったのか一時停止なのかを区別する。終端に達していれば「終了」。
            'finished': bool(
                not playing
                and elapsed is not None
                and total is not None
                and elapsed >= total - STALL_AFTER_SEC
            ),
            'stamp': wall_sec,
        }
