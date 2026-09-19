"""実機で測るための道具（#78、Phase 7 の段 0〜2）。

**実機に触れる時間は短い。当日に測り方を考えない。** 実機が来る前に mock で
動かしておき、当日は同じコマンドを打つだけにする。

ここに置くのは 2 つ:

- `summarize_telemetry` … テレメトリを一定時間受けて、項目ごとに min / max /
  欠損 / 実測レートを出す（段 0）。**宣言と実物の食い違いを名指しする**
- `stop_time` … E-STOP とハートビート断で、指令がゼロになるまでの時間（段 1）

遅延（段 2）は既存の `whill latency` をそのまま使う。道具を増やさない。

## rclpy は使わない

CLI は uv 側で動く（設計原則 5）。指令トピックを見るところだけ `ros2 topic echo`
を子プロセスで呼ぶ。`whill doctor` が `ros2 topic list` を呼ぶのと同じ扱い。
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

ZERO_EPS = 1e-6
"""これ以下なら「ゼロ」とみなす。指令は float なので厳密比較しない。"""

MOVING_EPS = 0.01
"""これを超えたら「動き出した」とみなす [m/s, rad/s]。"""


# ---- 段 0: テレメトリの記録 --------------------------------------------------


@dataclass
class ItemStats:
    """1 項目ぶんの記録。"""

    name: str
    driver: str
    unit: str | None = None
    expected: bool = True
    """そのモードで起動するはずのドライバか。**起動していないものを「値が無い」と
    騒がない**（gateway は起動していないドライバの項目も送る）。"""
    count: int = 0
    missing: int = 0
    """値が来なかった回数（`value` が null）。**「0」と「不明」を混ぜない。**"""
    values: list[float] = field(default_factory=list)
    levels: dict[str, int] = field(default_factory=dict)

    @property
    def low(self) -> float | None:
        return min(self.values) if self.values else None

    @property
    def high(self) -> float | None:
        return max(self.values) if self.values else None

    @property
    def median(self) -> float | None:
        return statistics.median(self.values) if self.values else None


def _items(frame: dict[str, Any]):
    for driver in frame.get('drivers') or []:
        for item in driver.get('items') or []:
            yield driver.get('driver', '?'), driver.get('expected', True), item
    for item in frame.get('derived') or []:
        yield item.get('driver', 'derived'), True, item


def collect_telemetry(frames: list[dict[str, Any]]) -> dict[str, ItemStats]:
    """受け取ったフレームを項目ごとにまとめる。時刻は使わない（純関数）。"""
    stats: dict[str, ItemStats] = {}
    for frame in frames:
        for driver, expected, item in _items(frame):
            name = item.get('name', '?')
            entry = stats.setdefault(name, ItemStats(
                name=name, driver=driver, unit=item.get('unit'), expected=expected))
            entry.count += 1
            value = item.get('value')
            if isinstance(value, (int, float)) and math.isfinite(value):
                entry.values.append(float(value))
            else:
                entry.missing += 1
            level = item.get('level', 'unknown')
            entry.levels[level] = entry.levels.get(level, 0) + 1
    return stats


def compare_with_declaration(stats: dict[str, ItemStats], declared: dict[str, str],
                             inputs_unavailable: set[str] | None = None,
                             ) -> dict[str, list[str]]:
    """宣言（`cr2-base.yaml`）と実物の食い違い。

    **同じ「値が出ない」でも原因が違うので、混ぜずに 4 つに分ける**:

    - `never_arrived` … 宣言にあるのに 1 度も来ない → トピック名か publish そのもの
    - `no_value` … 来ているが値が入っていない → フィールド名
    - `inputs_unavailable` … 入力が**そのモードに無い**派生項目 → 故障ではない
      （mock には scan-to-map localizer が居ないので `yaw_rate_vs_ndt` は出ない）
    - `undeclared` … 宣言に無いのに来た

    そのモードで起動しないドライバの項目（gateway は `expected: false` を付けて
    送る）は、どれにも数えない。**起動していないものを故障として数えない。**
    """
    inputs_unavailable = inputs_unavailable or set()
    live = {name: entry for name, entry in stats.items() if entry.expected}
    return {
        'never_arrived': sorted(set(declared) - set(stats) - inputs_unavailable),
        'no_value': sorted(name for name, entry in live.items()
                           if name in declared and not entry.values
                           and name not in inputs_unavailable),
        'inputs_unavailable': sorted(
            name for name in inputs_unavailable
            if name in stats and not stats[name].values),
        'undeclared': sorted(set(live) - set(declared)),
    }


def telemetry_markdown(stats: dict[str, ItemStats], seconds: float,
                       diff: dict[str, list[str]]) -> str:
    """`docs/measurements/` にそのまま貼れる形。"""
    lines = [
        '| 項目 | ドライバ | 単位 | 受信 | 実測 Hz | 最小 | 中央 | 最大 | 値なし | level |',
        '|---|---|---|---|---|---|---|---|---|---|',
    ]
    for name in sorted(stats):
        s = stats[name]
        levels = ' '.join(f'{k}:{v}' for k, v in sorted(s.levels.items()))
        def fmt(v):
            return '—' if v is None else f'{v:.3g}'
        lines.append(
            f'| {s.name} | {s.driver} | {s.unit or "—"} | {s.count} | '
            f'{s.count / seconds:.1f} | {fmt(s.low)} | {fmt(s.median)} | {fmt(s.high)} | '
            f'{s.missing} | {levels} |')

    notes = []
    if diff['never_arrived']:
        notes.append(f'- **宣言にあるのに 1 度も来なかった**: {", ".join(diff["never_arrived"])}'
                     '（トピック名か publish そのものを疑う）')
    if diff['no_value']:
        notes.append(f'- **来ているが値が入っていない**: {", ".join(diff["no_value"])}'
                     '（フィールド名を疑う）')
    if diff.get('inputs_unavailable'):
        notes.append(f'- 入力がこのモードに無いので出ない（故障ではない）: '
                     f'{", ".join(diff["inputs_unavailable"])}')
    if diff['undeclared']:
        notes.append(f'- 宣言に無いのに来た: {", ".join(diff["undeclared"])}')
    if not any(diff[key] for key in ('never_arrived', 'no_value', 'undeclared')):
        notes.append('- 宣言と実物の食い違いなし')
    return '\n'.join([*lines, '', *notes])


async def record_telemetry(url: str, token: str, *, seconds: float) -> list[dict[str, Any]]:
    """テレメトリのフレームを集める。"""
    from whill_cli.tap import tap

    frames: list[dict[str, Any]] = []

    def on_frame(frame: dict[str, Any]) -> None:
        if frame.get('type') == 'telemetry':
            frames.append(frame)

    await tap(url, token, seconds=seconds, streams=['telemetry'], on_frame=on_frame)
    return frames


# ---- 段 1: 止まるまでの時間 --------------------------------------------------


@dataclass
class StopRun:
    """1 回ぶんの測定。"""

    trigger: str
    """`estop` か `heartbeat`。"""
    seconds: float | None
    """指令を止めてからゼロが出るまで。None は時間内にゼロが出なかった。"""


def parse_twist_csv(line: str) -> tuple[float, float] | None:
    """`ros2 topic echo --csv` の 1 行から (vx, wz) を取る。

    Twist は `linear.x,linear.y,linear.z,angular.x,angular.y,angular.z` の順。
    読めない行（警告など）は None を返して捨てる。
    """
    parts = [p.strip() for p in line.split(',')]
    if len(parts) < 6:
        return None
    try:
        values = [float(p) for p in parts[:6]]
    except ValueError:
        return None
    return values[0], values[5]


def is_zero(sample: tuple[float, float]) -> bool:
    return abs(sample[0]) <= ZERO_EPS and abs(sample[1]) <= ZERO_EPS


def is_moving(sample: tuple[float, float]) -> bool:
    return abs(sample[0]) > MOVING_EPS or abs(sample[1]) > MOVING_EPS


def summarize_stops(runs: list[StopRun]) -> dict[str, dict[str, float | int]]:
    """トリガごとに中央値・最大・失敗数。**平均は出さない**（最悪値が知りたい）。"""
    result: dict[str, dict[str, float | int]] = {}
    for trigger in sorted({run.trigger for run in runs}):
        times = [run.seconds for run in runs if run.trigger == trigger and run.seconds is not None]
        failed = sum(1 for run in runs if run.trigger == trigger and run.seconds is None)
        result[trigger] = {
            'n': sum(1 for run in runs if run.trigger == trigger),
            'failed': failed,
            'median_ms': statistics.median(times) * 1000 if times else float('nan'),
            'max_ms': max(times) * 1000 if times else float('nan'),
        }
    return result


class CommandWatcher:
    """指令トピックを `ros2 topic echo` で覗く。

    rclpy を CLI に持ち込まないための子プロセス（`whill doctor` と同じ扱い）。
    """

    def __init__(self, topic: str, env: dict[str, str]) -> None:
        self._topic = topic
        self._proc = subprocess.Popen(
            ['ros2', 'topic', 'echo', topic, 'geometry_msgs/msg/Twist', '--csv'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self._samples: list[tuple[float, tuple[float, float]]] = []
        self._stop = False
        import threading
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        for line in self._proc.stdout:
            if self._stop:
                break
            sample = parse_twist_csv(line)
            if sample is not None:
                self._samples.append((time.monotonic(), sample))

    def wait_for(self, predicate, *, timeout: float, after: float) -> float | None:
        """`after` 以降に届いた指令のうち、条件を満たす最初の時刻を返す。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for stamp, sample in list(self._samples):
                if stamp >= after and predicate(sample):
                    return stamp
            time.sleep(0.005)
        return None

    def close(self) -> None:
        self._stop = True
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()


async def measure_stop(url: str, token: str, watcher: CommandWatcher, *, trigger: str,
                       vx: float, timeout: float) -> StopRun:
    """動かしてから止める合図を送り、指令がゼロになるまでを測る。

    **車輪を浮かせた状態で使う道具。** 実際に車体が動く。
    """
    import websockets

    from whill_stackd import tls

    async with await asyncio.wait_for(
            websockets.connect(url, **tls.connect_kwargs(url)), 10) as ws:
        await ws.recv()
        await ws.send(json.dumps({'type': 'auth', 'token': token}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if reply.get('type') == 'error':
            raise RuntimeError(f'認証に失敗した: {reply.get("reason")}')

        # 動かす。gateway のハートビート監視に合わせて 10 Hz で送り続ける。
        start = time.monotonic()
        moving_at = None
        while time.monotonic() - start < timeout:
            await ws.send(json.dumps({'type': 'manual_vel', 'vx': vx, 'wz': 0.0}))
            await asyncio.sleep(0.1)
            moving_at = watcher.wait_for(is_moving, timeout=0.01, after=start)
            if moving_at is not None:
                break
        if moving_at is None:
            raise RuntimeError('指令が動き出さない。twist_mux と gateway の配線を確認すること')

        if trigger == 'estop':
            triggered = time.monotonic()
            await ws.send(json.dumps({'type': 'estop', 'engage': True}))
        else:
            # ハートビート断: 送るのをやめて接続だけ維持する
            triggered = time.monotonic()

        zero_at = watcher.wait_for(is_zero, timeout=timeout, after=triggered)

        if trigger == 'estop':
            await ws.send(json.dumps({'type': 'estop', 'engage': False}))
            await asyncio.sleep(0.2)

    return StopRun(trigger=trigger, seconds=None if zero_at is None else zero_at - triggered)
