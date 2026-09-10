"""ジャイロと localizer の yaw 変化率の乖離のテスト。

`yaw_vs_ndt.py` は rclpy に依存せず、時刻を全部引数で受け取るので決定的に
検証できる。

見たいのは 2 つ:

  1. **健全なときに黙っていること。** 誤検知を出す指標はそのうち誰も見なくなる
  2. **TF 凍結で鳴ること。** これを見るために作った指標なので、鳴らなければ
     存在意義が無い
"""

from __future__ import annotations

import math

import pytest

from whill_gateway.yaw_vs_ndt import (
    MAX_GAP_SEC,
    WINDOW_SEC,
    YawRateVsNdt,
    orientation_is_provided,
    wrap_deg,
)

# cr2-base.yaml の derived_telemetry と揃えること。
WARN, CRIT = 5.0, 10.0

IMU_HZ = 100.0
NDT_HZ = 10.0


def drive(metric: YawRateVsNdt, *, seconds: float, turn_deg_s: float,
          ndt_turn_deg_s: float | None = None, start: float = 100.0,
          yaw0: float = 0.0) -> list[float | None]:
    """一定の旋回速度で回し、評価値の列を返す。

    `ndt_turn_deg_s` を別に与えると、localizer だけ別の速さで回る
    （TF 凍結は 0 を渡す）。
    """
    ndt_rate = turn_deg_s if ndt_turn_deg_s is None else ndt_turn_deg_s
    out: list[float | None] = []
    imu_step, ndt_step = 1.0 / IMU_HZ, 1.0 / NDT_HZ
    n_imu = int(seconds * IMU_HZ)
    next_ndt = start
    yaw = yaw0
    for i in range(n_imu + 1):
        t = start + i * imu_step
        metric.observe_imu(t, turn_deg_s)
        if t >= next_ndt:
            yaw = yaw0 + ndt_rate * (t - start)
            metric.observe_ndt(t, wrap_deg(yaw))
            out.append(metric.value)
            next_ndt += ndt_step
    return out


def settled(values: list[float | None]) -> list[float]:
    """窓が埋まったあとの値だけ。"""
    return [v for v in values if v is not None]


# ---- 健全なとき -------------------------------------------------------------


def test_nothing_before_any_input():
    metric = YawRateVsNdt()
    assert metric.value is None
    assert metric.state()['value'] is None


def test_still_robot_reports_no_divergence():
    values = settled(drive(YawRateVsNdt(), seconds=5.0, turn_deg_s=0.0))
    assert values
    assert max(values) == pytest.approx(0.0, abs=1e-6)


def test_matching_turn_reports_no_divergence():
    """両方が同じ速さで回っていれば乖離は 0。"""
    values = settled(drive(YawRateVsNdt(), seconds=5.0, turn_deg_s=30.0))
    assert values
    assert max(values) < 0.5


def test_wrapping_does_not_produce_a_spike():
    """179 度と -179 度の差は 358 度ではなく 2 度。

    素朴に引くと**旋回のたびに crit が出る。**
    """
    values = settled(drive(YawRateVsNdt(), seconds=20.0, turn_deg_s=40.0,
                           yaw0=170.0))
    assert values
    assert max(values) < 0.5, f'折り返しで跳ねた: {max(values)}'


def test_reverse_turn_is_fine():
    values = settled(drive(YawRateVsNdt(), seconds=5.0, turn_deg_s=-25.0))
    assert max(values) < 0.5


# ---- TF 凍結 ----------------------------------------------------------------


def test_frozen_localizer_during_a_turn_is_caught():
    """これを見るために作った指標。"""
    values = settled(drive(YawRateVsNdt(), seconds=5.0, turn_deg_s=20.0,
                           ndt_turn_deg_s=0.0))
    assert values
    # 乖離は旋回速度そのものになる。
    assert values[-1] == pytest.approx(20.0, abs=1.0)
    assert values[-1] >= CRIT


def test_a_slow_turn_with_a_frozen_localizer_reaches_warn():
    values = settled(drive(YawRateVsNdt(), seconds=5.0, turn_deg_s=6.0,
                           ndt_turn_deg_s=0.0))
    assert WARN <= values[-1] < CRIT


def test_a_stationary_frozen_localizer_says_nothing():
    """**限界。** 止まっていれば両方 0 で、凍結していても乖離は出ない。

    「乖離が小さい = localization が正しい」ではない。この性質を知らずに
    使うと、止まっているあいだの安心が嘘になる。
    """
    values = settled(drive(YawRateVsNdt(), seconds=5.0, turn_deg_s=0.0,
                           ndt_turn_deg_s=0.0))
    assert max(values) == pytest.approx(0.0, abs=1e-6)


def test_partially_frozen_localizer_shows_the_difference():
    """完全な凍結だけでなく、遅れも出る。"""
    values = settled(drive(YawRateVsNdt(), seconds=5.0, turn_deg_s=30.0,
                           ndt_turn_deg_s=20.0))
    assert values[-1] == pytest.approx(10.0, abs=1.0)


# ---- 測れないとき -----------------------------------------------------------


def test_window_must_fill_before_reporting():
    """窓が埋まる前に数字を出さない。標本が足りないと暴れる。"""
    metric = YawRateVsNdt()
    values = drive(metric, seconds=WINDOW_SEC * 0.3, turn_deg_s=30.0)
    assert all(v is None for v in values)
    assert '窓' in metric.state()['reason']


def test_pose_before_any_gyro_is_not_evaluated():
    metric = YawRateVsNdt()
    metric.observe_ndt(100.0, 0.0)
    assert metric.value is None
    assert 'ジャイロ' in metric.state()['reason']


def test_a_gyro_gap_restarts_the_integration():
    """途切れた区間を補間で埋めると「回っていなかった」ことにしてしまう。"""
    metric = YawRateVsNdt()
    drive(metric, seconds=3.0, turn_deg_s=20.0)
    assert metric.value is not None

    # ジャイロが途切れる
    metric.observe_imu(103.0 + MAX_GAP_SEC + 0.1, 20.0)
    assert metric.value is None
    assert '途切れ' in metric.state()['reason']


def test_repeated_stamps_do_not_break_the_integration():
    """同じ stamp の再送で 0 除算しない。"""
    metric = YawRateVsNdt()
    for _ in range(3):
        metric.observe_imu(100.0, 10.0)
    drive(metric, seconds=3.0, turn_deg_s=10.0, start=100.0)
    assert metric.value is not None


# ---- 姿勢が未推定であること -------------------------------------------------


def test_orientation_is_treated_as_absent_when_covariance_is_negative():
    """`sensor_msgs/Imu` は covariance[0] < 0 で「姿勢は出していない」を表す。

    RT-USB-9AXIS-00 が実際にこれ（実 bag の全 23509 通）。見ないと
    **「常に yaw 0 度」を正しい値として表示する**ことになる。
    """
    assert orientation_is_provided([0.01] + [0.0] * 8) is True
    assert orientation_is_provided([-1.0] + [0.0] * 8) is False
    assert orientation_is_provided(None) is False
    assert orientation_is_provided([]) is False


def test_extract_yaw_returns_none_for_an_unestimated_orientation():
    from types import SimpleNamespace

    from whill_gateway.telemetry_spec import extract

    q = SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
    absent = SimpleNamespace(orientation=q, orientation_covariance=[-1.0] + [0.0] * 8)
    assert extract(absent, '__yaw_deg') is None

    present = SimpleNamespace(orientation=q, orientation_covariance=[0.01] + [0.0] * 8)
    assert extract(present, '__yaw_deg') == pytest.approx(0.0)


def test_yaw_rate_is_read_in_degrees():
    from types import SimpleNamespace

    from whill_gateway.telemetry_spec import extract

    msg = SimpleNamespace(angular_velocity=SimpleNamespace(z=math.pi / 2))
    assert extract(msg, '__yaw_rate_deg') == pytest.approx(90.0)


# ---- 角度の畳み込み ---------------------------------------------------------


@pytest.mark.parametrize('angle,expected', [
    (0.0, 0.0), (180.0, -180.0), (-180.0, -180.0),
    (358.0, -2.0), (-358.0, 2.0), (540.0, -180.0),
])
def test_wrap(angle, expected):
    assert wrap_deg(angle) == pytest.approx(expected)


# ---- 宣言との整合 -----------------------------------------------------------


def test_the_declaration_matches_what_is_computed():
    """宣言に無い名前を計算しても、閾値も単位も付かないまま捨てられる。"""
    import yaml
    from whill_gateway.driver_telemetry import DERIVED_YAW_RATE
    from whill_params import registry as reg

    base = yaml.safe_load(
        (reg.config_root() / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
    declared = {d['name']: d for d in base['derived_telemetry']}
    assert DERIVED_YAW_RATE in declared

    spec = declared[DERIVED_YAW_RATE]
    assert spec['unit'] == 'deg/s'
    assert spec['compare'] == 'above'
    # 実測（健全な代表 bag で最大 3.06 deg/s）より上に置くこと。
    assert spec['warn'] > 3.06
    assert spec['crit'] > spec['warn']
    assert set(spec['inputs']) == {'/imu/data_rep145', '/pcl_pose'}
