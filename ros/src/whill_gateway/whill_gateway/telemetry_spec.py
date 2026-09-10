"""ドライバのテレメトリ宣言を解決し、値と level を保持する。

**rclpy に依存しない。** 宣言（素の辞書）と、抽出済みの値と時刻を渡すだけなので、
ROS を立てずに検証できる。ROS の購読は `driver_telemetry.py` が持つ。

## 宣言はどこにあるか

`config/robots/cr2-base.yaml` の `drivers.*.telemetry`。Phase 0 でスキーマを
確定させたまま、これまで誰も読んでいなかった。

```yaml
telemetry:
  - {name: battery, topic: /whill/states/model_cr2, field: battery_power,
     unit: "%", widget: bar, warn: 30, crit: 15, compare: below}
```

## 閾値の判定をここでやる理由

`warn` / `crit` / `compare` の評価は gateway 側で完結させ、UI には結果
（`level`）だけ渡す。判定を UI に置くと、`whill doctor` や CLI から見たときに
**画面と違う答え**が出る。閾値を読む場所は 1 つにする。

## 「値が無い」を 0 にしない

一度も来ていなければ `value=None` / `level='unknown'`、来てから途絶えたら
`level='stale'` で**値は残す**。バッテリー 0 % と「バッテリー不明」を同じ絵に
するのが、この画面で作りうる一番まずい誤読。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from whill_gateway import protocol

LEVEL_UNKNOWN = 'unknown'
LEVEL_STALE = 'stale'
LEVEL_OK = 'ok'
LEVEL_WARN = 'warn'
LEVEL_CRIT = 'crit'

RATE_WINDOW_SEC = 4.0
"""受信レートを平均する窓（実時間）。

短いと 2.5 Hz のトピックで標本が足りず数字が暴れる。長いと停止に気づくのが遅れる。
"""

RATE_MAX_SAMPLES = 512
"""窓に貯める到着時刻の上限。

100 Hz の IMU でも窓に入るのは 400 点だが、宣言外の高レートなトピックを
指されたときにメモリが伸び続けないよう蓋をしておく。
"""

FIELD_RATE = '__rate'
FIELD_YAW_DEG = '__yaw_deg'
FIELD_YAW_RATE_DEG = '__yaw_rate_deg'
PSEUDO_FIELDS = frozenset({FIELD_RATE, FIELD_YAW_DEG, FIELD_YAW_RATE_DEG})
"""メッセージの中に無い計算値。宣言で `__` 始まりの `field` として書かれる。

`__rate`          そのトピックの受信レートの**実測**（宣言値ではない）
`__yaw_deg`       quaternion から取り出した yaw を度で。
                  **姿勢が未推定なら None**（`orientation_covariance[0] < 0`）
`__yaw_rate_deg`  `angular_velocity.z` を度/秒で
"""

MIN_STALE_SEC = 3.0
"""これより短い「古い」判定はしない。

宣言レートが高いトピック（100 Hz の IMU）で `5 / rate_hz` をそのまま使うと
0.05 s になり、一瞬の取りこぼしで stale が点滅する。
"""


class TelemetryError(Exception):
    """宣言が契約を満たしていない。"""


@dataclass
class TelemetrySpec:
    """telemetry 宣言 1 件。"""

    name: str
    driver: str
    topic: str
    field: str
    widget: str
    unit: str | None = None
    warn: float | None = None
    crit: float | None = None
    compare: str = 'none'
    description: str = ''
    rate_hz: float | None = None
    """`publishes` に書かれた宣言レート。

    `__rate` の**値としては使わない**（実測を出すのが目的）。stale と
    判定するまでの猶予を決めるためだけに持つ。
    """

    @property
    def stale_after(self) -> float:
        if not self.rate_hz or self.rate_hz <= 0:
            return MIN_STALE_SEC
        return max(MIN_STALE_SEC, 5.0 / self.rate_hz)


def level_of(value: float | None, spec: TelemetrySpec) -> str:
    """閾値を評価する。値が無いときは呼ばないこと（`unknown` は上位が付ける）。"""
    if value is None:
        return LEVEL_UNKNOWN
    if spec.compare == 'above':
        if spec.crit is not None and value >= spec.crit:
            return LEVEL_CRIT
        if spec.warn is not None and value >= spec.warn:
            return LEVEL_WARN
    elif spec.compare == 'below':
        if spec.crit is not None and value <= spec.crit:
            return LEVEL_CRIT
        if spec.warn is not None and value <= spec.warn:
            return LEVEL_WARN
    return LEVEL_OK


# ---- 宣言の読み取り ---------------------------------------------------------


def load_specs(base: dict[str, Any], robot: dict[str, Any] | None = None,
               ) -> list[TelemetrySpec]:
    """`cr2-base.yaml` の宣言を読み、個体の上書きを適用する。

    `name` は**全ドライバを通して一意**であることを要求する。上書き
    （`telemetry_overrides`）のキーが平坦な名前空間なので、重複を許すと
    「どちらに効いたか分からない上書き」ができる。
    """
    specs: list[TelemetrySpec] = []
    seen: dict[str, str] = {}

    for driver, decl in (base.get('drivers') or {}).items():
        # publishes の宣言レートを topic から引けるようにしておく。
        rates = {entry['topic']: entry.get('rate_hz')
                 for entry in (decl.get('publishes') or [])}
        for item in (decl.get('telemetry') or []):
            name = item['name']
            if name in seen:
                raise TelemetryError(
                    f'telemetry の name が重複している: {name} '
                    f'({seen[name]} と {driver})')
            seen[name] = driver
            field_name = item['field']
            if field_name.startswith('__') and field_name not in PSEUDO_FIELDS:
                # typo した疑似フィールドは、メッセージにも当然無いので
                # 「宣言したのに永久に値が出ない」になる。ここで落とす。
                raise TelemetryError(
                    f'{name}: 未知の疑似フィールド {field_name}'
                    f'（使えるのは {sorted(PSEUDO_FIELDS)}）')
            specs.append(TelemetrySpec(
                name=name,
                driver=driver,
                topic=item['topic'],
                field=item['field'],
                widget=item['widget'],
                unit=item.get('unit'),
                warn=item.get('warn'),
                crit=item.get('crit'),
                compare=item.get('compare', 'none'),
                description=item.get('description', ''),
                rate_hz=rates.get(item['topic']),
            ))

    _apply_overrides(specs, (robot or {}).get('telemetry_overrides') or {})
    return specs


def _apply_overrides(specs: list[TelemetrySpec], overrides: dict[str, Any]) -> None:
    """個体 yaml の `telemetry_overrides` を適用する。

    存在しない名前は**エラーにする。** 黙って無視すると、typo した上書きが
    「書いたのに効かない」まま本番に残る（`param_overrides` と同じ方針）。
    """
    by_name = {spec.name: spec for spec in specs}
    for name, override in overrides.items():
        spec = by_name.get(name)
        if spec is None:
            raise TelemetryError(
                f'telemetry_overrides の "{name}" は cr2-base.yaml のどの '
                f'telemetry にも一致しない')
        if not isinstance(override, dict):
            raise TelemetryError(f'telemetry_overrides.{name} がオブジェクトでない')
        for key, value in override.items():
            if key not in ('warn', 'crit'):
                # 閾値以外を個体ごとに変えられるようにしない。topic や field を
                # 個体で差し替えると、同型 3 台という前提が崩れる。
                raise TelemetryError(
                    f'telemetry_overrides.{name}.{key} は上書きできない'
                    f'（warn と crit のみ）')
            if value is not None and not isinstance(value, (int, float)):
                raise TelemetryError(f'telemetry_overrides.{name}.{key} が数値でない')
            setattr(spec, key, None if value is None else float(value))


DERIVED_DRIVER = 'derived'
"""派生テレメトリの見かけ上の所属。

単一のドライバに属さないので、drivers パネルでは最下段に別枠で出す。
"""


def load_derived(base: dict[str, Any]) -> list[TelemetrySpec]:
    """`derived_telemetry` を読む。

    購読はしない（複数トピックから計算するもの）。値は gateway 側が
    `set_value` で入れる。
    """
    specs = []
    for item in (base.get('derived_telemetry') or []):
        specs.append(TelemetrySpec(
            name=item['name'],
            driver=DERIVED_DRIVER,
            # 単一トピックに属さない。レート測定の対象にもしない。
            topic='',
            field=item['name'],
            widget=item['widget'],
            unit=item.get('unit'),
            warn=item.get('warn'),
            crit=item.get('crit'),
            compare=item.get('compare', 'none'),
            description=item.get('description', ''),
        ))
    return specs


def expected_drivers(base: dict[str, Any], mode: str) -> set[str]:
    """そのモードで起動するはずのドライバ。

    「値が来ていない」と「そもそも起動していない」を UI が区別するために要る。
    現地で「センサが壊れた」のか「launch に入っていない」のかを切り分けられないと、
    見当違いのところを探すことになる。
    """
    decl = (base.get('modes') or {}).get(mode) or {}
    return set(decl.get('drivers') or [])


# ---- 値の取り出し -----------------------------------------------------------


def extract(message: Any, field_name: str) -> float | None:
    """メッセージから宣言された field を数値として取り出す。

    `a.b.c` のドット区切りに対応する（実ドライバのメッセージでは
    `header.stamp` のような入れ子が出てくる）。

    取り出せなければ **`None` を返して黙る。** 宣言と実メッセージが食い違って
    いるのは直すべきことだが、テレメトリ 1 件のために gateway を落とすと、
    E-stop も俯瞰図も一緒に止まる（設計原則 4）。level が `unknown` のまま
    動かないことで気づける。
    """
    if field_name == FIELD_YAW_DEG:
        return _yaw_deg(message)
    if field_name == FIELD_YAW_RATE_DEG:
        return _yaw_rate_deg(message)

    current: Any = message
    for part in field_name.split('.'):
        current = getattr(current, part, None)
        if current is None:
            return None
    # bool は int の派生。True を 1.0 として通すと、状態フラグが数値の顔をする。
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    return float(current)


def _yaw_deg(message: Any) -> float | None:
    """quaternion から yaw を度で。`orientation` を持つメッセージ用。

    **姿勢が未推定なら None を返す。** `sensor_msgs/Imu` は
    `orientation_covariance[0] < 0` で「姿勢は出していない」を表す規約で、
    そのとき四元数は単位のまま置かれる。見ないと**「常に yaw 0 度」を
    正しい値として表示する**ことになる（RT-USB-9AXIS-00 が実際にこれ）。
    """
    covariance = getattr(message, 'orientation_covariance', None)
    if covariance is not None and not _orientation_provided(covariance):
        return None
    q = getattr(message, 'orientation', None)
    if q is None:
        return None
    try:
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))
    except (AttributeError, TypeError):
        return None
    return math.degrees(yaw)


def _orientation_provided(covariance: Any) -> bool:
    try:
        return float(covariance[0]) >= 0.0
    except (TypeError, IndexError, ValueError):
        return False


def _yaw_rate_deg(message: Any) -> float | None:
    """`angular_velocity.z` を度/秒で。"""
    angular = getattr(message, 'angular_velocity', None)
    z = getattr(angular, 'z', None)
    if not isinstance(z, (int, float)) or isinstance(z, bool):
        return None
    return math.degrees(float(z))


# ---- 受信の記録 -------------------------------------------------------------


class RateTracker:
    """トピックの**実測**受信レート。

    宣言値（`publishes.rate_hz`）を返してはいけない。この指標の目的は
    「宣言が 10 Hz なのに実際は 4 Hz」を見つけることなので、宣言値を返す
    実装は意味を反転させる。
    """

    def __init__(self) -> None:
        self._arrivals: deque[float] = deque(maxlen=RATE_MAX_SAMPLES)

    def observe(self, wall_sec: float) -> None:
        self._arrivals.append(wall_sec)

    def rate(self, wall_sec: float) -> float | None:
        cutoff = wall_sec - RATE_WINDOW_SEC
        while self._arrivals and self._arrivals[0] < cutoff:
            self._arrivals.popleft()
        if len(self._arrivals) < 2:
            return None
        # 窓の実長ではなく最初と最後の差で割る。窓を満たしていない立ち上がりで
        # 過小に出るのを避ける。
        span = self._arrivals[-1] - self._arrivals[0]
        if span <= 0:
            return None
        return (len(self._arrivals) - 1) / span


@dataclass
class Reading:
    value: float | None = None
    at: float | None = None
    """最後に値が入った実時間。`None` なら一度も来ていない。"""


class TelemetryStore:
    """宣言ごとの現在値。時刻はすべて引数で受け取る。"""

    def __init__(self, specs: list[TelemetrySpec], expected: set[str],
                 derived: list[TelemetrySpec] | None = None) -> None:
        self.specs = specs
        self.derived = derived or []
        self.expected = expected
        self._readings: dict[str, Reading] = {
            s.name: Reading() for s in [*specs, *self.derived]}
        # レートはトピック単位。同じトピックを見る宣言が複数あっても 1 つで済む。
        self._rates: dict[str, RateTracker] = {}
        self._seen: set[str] = set()
        for spec in specs:
            self._rates.setdefault(spec.topic, RateTracker())

    # ---- 記録 --------------------------------------------------------------

    def observe_topic(self, topic: str, wall_sec: float) -> None:
        """そのトピックにメッセージが来たことだけを記録する（レート用）。"""
        tracker = self._rates.get(topic)
        if tracker is not None:
            tracker.observe(wall_sec)
            self._seen.add(topic)

    def set_value(self, name: str, value: float | None, wall_sec: float) -> None:
        reading = self._readings.get(name)
        if reading is None:
            return
        if value is None or not math.isfinite(value):
            # NaN を「値が来た」と扱うと、壊れたセンサが ok に見える。
            return
        reading.value = float(value)
        reading.at = wall_sec

    def rate_of(self, topic: str, wall_sec: float) -> float | None:
        tracker = self._rates.get(topic)
        return None if tracker is None else tracker.rate(wall_sec)

    def _rate_item(self, spec: TelemetrySpec,
                   wall_sec: float) -> tuple[float | None, str, float | None]:
        """`__rate` の値と level。

        **途絶えたら `unknown` ではなく 0 Hz にする。** velodyne が落ちたときに
        見たいのは「レートが不明」ではなく「レートが 0 で crit」。ここを
        `unknown` にすると、一番気づきたい故障が一番目立たない色になる。

        一度も来ていないトピックだけが `unknown`。
        """
        if spec.topic not in self._seen:
            return None, LEVEL_UNKNOWN, None
        measured = self.rate_of(spec.topic, wall_sec)
        value = 0.0 if measured is None else measured
        return value, level_of(value, spec), None

    # ---- 出力 --------------------------------------------------------------

    def item(self, spec: TelemetrySpec, wall_sec: float) -> dict[str, Any]:
        if spec.field == FIELD_RATE:
            value, level, age = self._rate_item(spec, wall_sec)
        else:
            reading = self._readings[spec.name]
            value, level, age = reading.value, LEVEL_UNKNOWN, None
            if reading.at is not None:
                age = wall_sec - reading.at
                level = (LEVEL_STALE if age > spec.stale_after
                         else level_of(value, spec))

        return {
            'name': spec.name,
            'driver': spec.driver,
            'topic': spec.topic,
            'value': None if value is None else round(value, 3),
            'unit': spec.unit,
            'widget': spec.widget,
            'level': level,
            'warn': spec.warn,
            'crit': spec.crit,
            'compare': spec.compare,
            'description': spec.description,
            # 「n 秒前」を出すため。stale の値を最新のように描かせない。
            'age': None if age is None else round(age, 2),
        }

    def frame(self, wall_sec: float) -> dict[str, Any]:
        """ドライバごとにまとめた 1 フレーム。

        平坦な一覧にしないのは、UI がドライバ単位のカードで出すため（#41）。
        並び替えを UI 側でやると、宣言の順序という手がかりが失われる。
        """
        drivers: dict[str, dict[str, Any]] = {}
        for spec in self.specs:
            entry = drivers.setdefault(spec.driver, {
                'driver': spec.driver,
                # そのモードで起動するはずか。「値が無い」と「起動していない」の
                # 区別に使う。
                'expected': spec.driver in self.expected,
                'items': [],
            })
            entry['items'].append(self.item(spec, wall_sec))
        return {
            'type': protocol.MSG_TELEMETRY,
            'drivers': list(drivers.values()),
            # 単一のドライバに属さないものは別枠。ドライバのカードに
            # 紛れ込ませると、どのセンサの話か読み違える。
            'derived': [self.item(spec, wall_sec) for spec in self.derived],
            'stamp': wall_sec,
        }
