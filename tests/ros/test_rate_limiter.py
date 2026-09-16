"""配信のレート制限（ADR-0007 で見つけた取りこぼし）。

**入力と同じレートに制限したときに落とさないこと。** カメラは 6 Hz で出るので
6 Hz に制限したが、到着が周期をわずかに下回るたびに 1 枚落ち、実測 4.3 Hz しか
通らなかった。レート制限は帯域を守るためのもので、宣言どおりに来た入力を
3 割捨てるのは目的から外れている。
"""

from __future__ import annotations

import pytest

from whill_gateway.telemetry import JITTER_TOLERANCE, RateLimiter


def _run(limiter: RateLimiter, arrivals: list[float]) -> int:
    return sum(1 for t in arrivals if limiter.allow(t))


def test_same_rate_input_is_not_dropped():
    """6 Hz の入力を 6 Hz に制限しても、揺れで落とさない。"""
    limiter = RateLimiter(6.0)
    # 到着は ±3 % 揺れる（実測のモックはこの程度）
    arrivals = [i / 6.0 + (0.003 if i % 2 else -0.003) for i in range(60)]
    assert _run(limiter, arrivals) >= 58


def test_faster_input_is_still_limited():
    """速い入力はちゃんと間引く。ここが緩むと帯域を守れない。"""
    limiter = RateLimiter(1.0)
    arrivals = [i / 30.0 for i in range(300)]   # 30 Hz を 10 秒
    passed = _run(limiter, arrivals)
    # 制限 1 Hz に対して、許容 1 割ぶんまでしか増えない
    assert 10 <= passed <= 12, passed


def test_tolerance_is_small_enough_to_keep_the_budget():
    assert 0 < JITTER_TOLERANCE <= 0.1


def test_zero_rate_passes_everything():
    limiter = RateLimiter(0.0)
    assert _run(limiter, [0.0, 0.0, 0.0]) == 3


@pytest.mark.parametrize('hz', [0.5, 2.0, 30.0])
def test_rate_can_be_changed_at_runtime(hz):
    """live パラメータなので走行中に変わる。"""
    limiter = RateLimiter(1.0)
    limiter.set_rate(hz)
    arrivals = [i / 100.0 for i in range(1000)]   # 100 Hz を 10 秒
    passed = _run(limiter, arrivals)
    assert abs(passed - hz * 10) <= max(2, hz)
