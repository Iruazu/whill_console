"""起動中のスタックに対して、live パラメータが本当に即時反映されるか試す。

`live: true` が実態と食い違っていると、UI のスライダーが「効いたように見えて
効いていない」状態になる。実機で最も危ない種類の嘘なので、Phase 2 で gateway に
繋ぐ前にここで潰す。

やり方は素朴に `ros2 param set` → `ros2 param get` の往復。rclpy でノードを
立ててサービスを叩くほうが速いが、gateway が実際に通る経路（ROS のパラメータ
サービス）と同じものを踏みたいので CLI を使う。速度より一致を優先する。

試した値は必ず元に戻す。戻さないと、probe したあとのスタックが
registry の想定と違う状態になる。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class ProbeResult:
    key: str
    ros_node: str
    param: str
    ok: bool
    detail: str
    original: Any = None


def _run(args: list[str], env: dict[str, str],
         timeout: float = 15.0) -> tuple[int, str, str]:
    """(returncode, stdout, stderr) を返す。

    stdout と stderr を混ぜないこと。CycloneDDS は起動のたびに
    「enx... optional interface was not found」等を stderr に吐くので、
    混ぜると値のパースがその警告を掴んで落ちる（実際に踏んだ）。
    """
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, '', 'タイムアウト'
    except FileNotFoundError:
        return 127, '', 'ros2 が見つからない'
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _format_value(value: Any) -> str:
    """ros2 param set に渡す文字列。配列は YAML フロー形式で渡す。"""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return '[' + ', '.join(_format_value(v) for v in value) + ']'
    return str(value)


def _probe_value(spec, current: Any) -> Any:
    """現在値と確実に違う、かつ範囲内の試験値を作る。

    同じ値を set しても「反映された」のか「無視された」のか区別できないので、
    必ず変化する値を選ぶ。
    """
    if spec.type == 'bool':
        return not current
    if spec.type == 'string':
        return current  # 文字列は live 検証の対象外（該当なし）

    def bump(value: float, rng: dict | None) -> float:
        lo = (rng or {}).get('min')
        hi = (rng or {}).get('max')
        step = (rng or {}).get('step') or 0.05
        if hi is not None and value + step <= hi:
            return round(value + step, 6)
        if lo is not None and value - step >= lo:
            return round(value - step, 6)
        # 範囲が 1 点しかない軸（差動二輪の vy など）は動かせない
        return value

    if spec.type == 'double_array':
        elements = spec.elements or []
        return [bump(v, (elements[i] or {}).get('range') if i < len(elements) else None)
                for i, v in enumerate(current)]
    if spec.type == 'int':
        return int(bump(float(current), spec.range))
    return bump(float(current), spec.range)


def _parse_get(output: str, spec) -> Any:
    """`ros2 param get` の出力から値を取り出す。

    出力は "Double value is: 0.7" / "Boolean value is: True" /
    "Double values are: [0.3, 0.0, 1.0]" のような形。DDS の警告が紛れても
    拾わないよう、該当する行だけを見る。
    """
    line = next((ln for ln in output.splitlines()
                 if ' is: ' in ln or ' are: ' in ln), '')
    _, _, tail = line.partition(' is: ')
    if not tail:
        _, _, tail = line.partition(' are: ')
    tail = tail.strip()
    if not tail:
        return None
    if spec.type == 'bool':
        return tail.lower().startswith('t')

    # 配列は "Double values are: array('d', [0.3, 0.0, 1.0])" の形で出る。
    # Python の array 表現なので、中の [] だけを取り出す。
    if tail.startswith('array('):
        start = tail.find('[')
        end = tail.rfind(']')
        if start == -1 or end == -1:
            return None
        tail = tail[start:end + 1]

    try:
        return json.loads(tail)
    except json.JSONDecodeError:
        return None


def probe_key(registry, key: str, env: dict[str, str]) -> ProbeResult:
    """1 つのパラメータについて set → get → 復元を試す。"""
    spec = registry.spec(key)
    node = registry.ros_node(spec.node)

    code, out, err = _run(['ros2', 'param', 'get', node, spec.name], env)
    if code != 0:
        return ProbeResult(key, node, spec.name, False, f'get 失敗: {err or out}')
    current = _parse_get(out, spec)
    if current is None:
        return ProbeResult(key, node, spec.name, False, f'現在値を読めない: {out}')

    trial = _probe_value(spec, current)
    if trial == current:
        return ProbeResult(key, node, spec.name, False,
                           '試験値を作れない（範囲が 1 点）', current)

    code, out, err = _run(
        ['ros2', 'param', 'set', node, spec.name, _format_value(trial)], env)
    if code != 0 or 'successful' not in out.lower():
        return ProbeResult(key, node, spec.name, False,
                           f'set 失敗: {out or err}', current)

    code, out, _ = _run(['ros2', 'param', 'get', node, spec.name], env)
    after = _parse_get(out, spec) if code == 0 else None

    # 値を戻す。probe のあとにスタックが registry の想定と違う状態で
    # 残らないようにする。
    _run(['ros2', 'param', 'set', node, spec.name, _format_value(current)], env)

    if after is None:
        return ProbeResult(key, node, spec.name, False, f'set 後の get 失敗: {out}', current)

    ok = _close_enough(after, trial)
    detail = 'OK' if ok else f'set は成功したが値が変わらない (期待 {trial} / 実際 {after})'
    return ProbeResult(key, node, spec.name, ok, detail, current)


def _close_enough(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close_enough(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def probe_all(registry, env: dict[str, str], keys: list[str] | None = None
              ) -> list[ProbeResult]:
    targets = keys if keys is not None else registry.live_keys()
    return [probe_key(registry, key, env) for key in targets]
