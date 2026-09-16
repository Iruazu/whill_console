"""Nav2 が動いているかの判定（#67）。

`nav2_status.py` は rclpy に依存せず、時刻を引数で受け取るので決定的に検証できる。

見たいのは、**真偽値 1 つでは同じ絵になっていた 3 つを区別すること**:

  1. Nav2 を起動しないモード（replay）
  2. 起動直後で、まだ上がりきっていない
  3. 起動しているはずなのに応答が無い（一番困る状態）
"""

from __future__ import annotations

import pytest
import yaml

from pathlib import Path

from whill_gateway.nav2_status import (
    STALE_AFTER_SEC,
    STARTUP_GRACE_SEC,
    STATE_ACTIVE,
    STATE_DOWN,
    STATE_INACTIVE,
    STATE_NOT_STARTED,
    STATE_STARTING,
    Nav2Watch,
    starts_nav2,
)

BASE = Path(__file__).resolve().parents[2] / 'config' / 'robots' / 'cr2-base.yaml'


def watch(started=True, at=0.0):
    return Nav2Watch(started=started, started_at=at)


def test_replay_is_not_a_failure():
    """replay は Nav2 を上げない（ADR-0004）。毎回赤くすると誰も見なくなる。"""
    nav = watch(started=False)
    assert nav.state(0.0) == STATE_NOT_STARTED
    assert nav.state(10_000.0) == STATE_NOT_STARTED


def test_starting_then_down_if_it_never_answers():
    nav = watch(at=100.0)
    assert nav.state(100.0) == STATE_STARTING
    assert nav.state(100.0 + STARTUP_GRACE_SEC - 0.1) == STATE_STARTING
    # 上がるはずの時間を過ぎても答えないなら、それは故障
    assert nav.state(100.0 + STARTUP_GRACE_SEC) == STATE_DOWN


@pytest.mark.parametrize('active, expected', [(True, STATE_ACTIVE), (False, STATE_INACTIVE)])
def test_answer_decides_active_or_inactive(active, expected):
    nav = watch()
    nav.observe(active=active, wall_sec=1.0)
    assert nav.state(1.0) == expected


def test_silence_after_an_answer_is_down():
    """一度は答えたのに黙った = 落ちた。active のまま固まらせない。"""
    nav = watch()
    nav.observe(active=True, wall_sec=1.0)
    assert nav.state(1.0 + STALE_AFTER_SEC - 0.1) == STATE_ACTIVE
    assert nav.state(1.0 + STALE_AFTER_SEC) == STATE_DOWN


def test_it_recovers_when_answers_come_back():
    nav = watch()
    nav.observe(active=True, wall_sec=1.0)
    assert nav.state(100.0) == STATE_DOWN
    nav.observe(active=True, wall_sec=100.0)
    assert nav.state(100.0) == STATE_ACTIVE


def test_modes_decide_whether_nav2_is_expected():
    """起動するかどうかは cr2-base.yaml の modes が正（設計原則 3）。"""
    base = yaml.safe_load(BASE.read_text('utf-8'))
    assert starts_nav2(base, 'mock') is True
    assert starts_nav2(base, 'real') is True
    assert starts_nav2(base, 'replay') is False
    # 宣言の無いモードは「起動する」側に倒す（起動しているのに黙るほうが困る）
    assert starts_nav2(base, 'no-such-mode') is True
