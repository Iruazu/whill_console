"""ジャイロの yaw 角速度と scan-to-map localizer の yaw 変化率の乖離。

**rclpy に依存しない。** 角度・角速度・時刻を渡すだけなので、ROS を立てずに
検証できる。

## 何を見たいのか

`cr2-base.yaml` の `derived_telemetry` にこう書いてある:

> localization 劣化（TF 凍結 → Nav2 abort）の早期検知に使う。
> 実機で最も再発している故障モード。

localizer が実質止まると `/pcl_pose` の yaw は動かないが、車体は回っている。
**ジャイロは回転を見ているので、その食い違いが直接の兆候になる。**

## 角度どうしを比べないのは、IMU が姿勢を出さないから

当初の計画は「IMU の yaw」と「localizer の yaw」を比べるものだった。実 bag
（`bags/2026-07-31-campus`）で確かめたところ、**`/imu/data_rep145` の
`orientation` は全 23509 通が単位四元数で、`orientation_covariance[0]` は
一貫して -1** だった。REP-145 の「姿勢は未推定」の表明で、既存スタックの
EKF も同じ理由で orientation を skip している（`ekf_odom.yaml` の注記 (3)）。

つまり比べるべき「IMU の yaw」は存在しない。角速度なら実在する
（±0.58 rad/s、全区間の積分は約 900 度ぶん）。

角速度どうしを比べるほうが、そもそもこの用途には向いている:

- 基準（オフセット）の推定が要らない。角度どうしだと IMU と map で yaw の
  基準が違い、生の差は約 180 度になる
- 積み上がった誤差に汚されない
- TF 凍結という**見たい故障そのもの**を直接見る

## 閾値は実測から決めた

同じ bag（localization は健全）で 1 秒窓の乖離を測ると:

    全体      中央 0.11  95% 1.12  99% 1.89  最大 3.53 deg/s
    旋回中    中央 0.58  95% 1.36  最大 1.85 deg/s

ジャイロと localizer の回帰係数は 0.9855（符号もスケールも一致）。
一方、旋回中に TF が凍結したときに出る値は、そのときの旋回速度そのもの
（この bag の旋回の中央値で約 15.7 deg/s）。

健全時の最大 3.53 と、故障時に出る 15.7 のあいだに閾値を置く。

## 限界: 回っていないときは何も言えない

止まっている車体では両方 0 なので、localizer が凍結していても乖離は出ない。
**「乖離が小さい = localization が正しい」ではない。** 動き出せば出る、という
性質の指標として使うこと。絶対的な確認は `/alignment_status` の fitness
（配車パネル）と、地図に重ねた LiDAR の見え方で行う。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

WINDOW_SEC = 1.0
"""比較する窓の長さ。

短いと 10 Hz の pose では標本が足りず数字が暴れる。長いと凍結に気づくのが
遅れる。実測はこの長さで取った（冒頭の数字）。
"""

MAX_GAP_SEC = 0.5
"""ジャイロがこの時間途切れたら評価しない。

補間で埋めると、届いていない区間を「回っていなかった」ことにしてしまう。
"""

GYRO_BUFFER_SEC = 5.0
"""ジャイロの積分値を保持する長さ。窓より十分長ければよい。"""


def wrap_deg(angle: float) -> float:
    """角度差を -180..180 に畳む。

    179 度と -179 度の差は 358 度ではなく 2 度。素朴に引くと**旋回のたびに
    crit が出る。**
    """
    return (angle + 180.0) % 360.0 - 180.0


def orientation_is_provided(covariance) -> bool:
    """`sensor_msgs/Imu` が姿勢を出しているか。

    REP-145 / `sensor_msgs/Imu` の規約で、`orientation_covariance[0]` が
    負なら「姿勢は未推定」。**RT-USB-9AXIS-00 は実際にこれを立てて単位
    四元数を出す。** 見ないと「常に yaw 0 度」を正しい値として表示する
    ことになる（実際に #39 でそうなっていた）。
    """
    try:
        return float(covariance[0]) >= 0.0
    except (TypeError, IndexError, ValueError):
        return False


@dataclass
class _Pose:
    stamp: float
    yaw_deg: float
    gyro_angle: float
    """その時刻までのジャイロの累積回転（度）。差だけを使うので原点は任意。"""


class YawRateVsNdt:
    """ジャイロと localizer の yaw 変化率の乖離。時刻はすべて引数で受け取る。"""

    def __init__(self, *, window_sec: float = WINDOW_SEC) -> None:
        self.window_sec = window_sec
        self._gyro: deque[tuple[float, float]] = deque()
        """(stamp, 累積回転)。pose の stamp に合わせて内挿するために持つ。"""
        self._last_imu: tuple[float, float] | None = None
        self._poses: deque[_Pose] = deque()
        self._value: float | None = None
        self._reason = 'まだ値が来ていない'

    # ---- 入力 --------------------------------------------------------------

    def observe_imu(self, stamp: float, rate_deg_s: float) -> None:
        """ジャイロの yaw 角速度（度/秒）。台形則で積分して溜める。"""
        if self._last_imu is None:
            self._gyro.append((stamp, 0.0))
            self._last_imu = (stamp, rate_deg_s)
            return

        last_stamp, last_rate = self._last_imu
        dt = stamp - last_stamp
        self._last_imu = (stamp, rate_deg_s)
        if dt <= 0:
            # 同じ stamp の再送や巻き戻り。積分に入れない。
            return
        if dt > MAX_GAP_SEC:
            # 途切れた。補間で埋めると、届いていない区間を「回っていなかった」
            # ことにしてしまう。積分をやり直す。
            self._gyro.clear()
            self._poses.clear()
            self._gyro.append((stamp, 0.0))
            self._reason = 'ジャイロが途切れた'
            self._value = None
            return

        total = self._gyro[-1][1] + 0.5 * (last_rate + rate_deg_s) * dt
        self._gyro.append((stamp, total))
        cutoff = stamp - GYRO_BUFFER_SEC
        while len(self._gyro) > 2 and self._gyro[0][0] < cutoff:
            self._gyro.popleft()

    def observe_ndt(self, stamp: float, yaw_deg: float) -> None:
        """localizer の pose。遅いほう（約 10 Hz）に合わせて評価する。"""
        angle = self._gyro_angle_at(stamp)
        if angle is None:
            self._reason = 'ジャイロがまだ来ていない'
            self._value = None
            return

        self._poses.append(_Pose(stamp, yaw_deg, angle))
        while len(self._poses) > 2 and stamp - self._poses[1].stamp >= self.window_sec:
            # 窓に必要な最古の 1 件だけ残す。
            self._poses.popleft()

        oldest = self._poses[0]
        span = stamp - oldest.stamp
        if span < self.window_sec * 0.5:
            self._reason = '窓が埋まっていない'
            self._value = None
            return

        ndt_rate = wrap_deg(yaw_deg - oldest.yaw_deg) / span
        gyro_rate = (angle - oldest.gyro_angle) / span
        self._value = abs(gyro_rate - ndt_rate)
        self._reason = ''

    def _gyro_angle_at(self, stamp: float) -> float | None:
        """pose の stamp における累積回転を内挿で求める。

        ジャイロ 100 Hz に対し pose は 10 Hz。**最新値で代用すると、旋回中に
        最大 10 ms ぶん（30 deg/s なら 0.3 度）ずれる。** 健全時の乖離が
        0.1 deg/s 台なので、この誤差は無視できない。
        """
        if len(self._gyro) < 2:
            return None
        if stamp <= self._gyro[0][0]:
            return self._gyro[0][1]
        if stamp >= self._gyro[-1][0]:
            return self._gyro[-1][1]
        # 後ろから探す。pose は概ね最新のジャイロの近くに来る。
        for i in range(len(self._gyro) - 1, 0, -1):
            t1, a1 = self._gyro[i]
            if t1 < stamp:
                continue
            t0, a0 = self._gyro[i - 1]
            if t0 <= stamp:
                ratio = (stamp - t0) / (t1 - t0)
                return a0 + ratio * (a1 - a0)
        return self._gyro[0][1]

    # ---- 出力 --------------------------------------------------------------

    @property
    def value(self) -> float | None:
        """乖離（度/秒）。測れていなければ None。**0 で埋めない。**"""
        return self._value

    def state(self) -> dict[str, Any]:
        """`telemetry` フレームに載せる補足。

        `reason` を出すのは、値が出ていない理由が UI から見えるようにするため。
        「なぜか数字が出ない」を追えない指標は使われなくなる。
        """
        return {
            'value': None if self._value is None else round(self._value, 2),
            'reason': self._reason,
        }
