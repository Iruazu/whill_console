"""TF の繋がりと、辺ごとの更新の途絶（#51）。

**rclpy に依存しない。** 親子と時刻を渡すだけなので、ROS を立てずに検証できる。
購読は `telemetry.py` が持つ。

## なぜ親子関係だけでは足りないか

以前の要約は「親子関係が変わったときだけ」配っていた。**TF が止まっても親子関係は
変わらない**ので、`map -> odom` を出す localizer が固まっても画面は健全なときと
同じ絵になっていた。TF 凍結は実機で最も再発している故障（TF 凍結 → Nav2 abort）。

そこで辺ごとに最後に届いた実時間を持ち、止まっている間も周期的に配る。

## 静的な辺と動的な辺を分ける

`/tf_static` の辺は更新されないのが正常。区別しないと「古い」の判定ができない。
一度でも `/tf_static` で届いた辺は静的とみなし、古さを判定しない。

## 期待値

- 動的な辺: `cr2-base.yaml` の `tf.dynamic`（閾値つき。代表 bag の実測から決めた）
- 静的な辺: 個体 yaml の `tf_static`

**来ていない期待の辺を「無い」と出す。** 無いフレームは木に現れないので、黙っていると
気づけない。親が違う場合も出す（宣言と実機が食い違っている）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from whill_gateway import protocol
from whill_gateway.telemetry_spec import RateTracker

LEVEL_OK = 'ok'
LEVEL_WARN = 'warn'
LEVEL_CRIT = 'crit'
LEVEL_STATIC = 'static'
LEVEL_UNJUDGED = 'unjudged'
"""期待値に無い動的な辺。閾値が無いので良し悪しを言わない（古さは出す）。"""


@dataclass(frozen=True)
class DynamicEdgeSpec:
    parent: str
    child: str
    warn_sec: float
    crit_sec: float
    source: str = ''


@dataclass
class _Edge:
    parent: str
    child: str
    static: bool
    last_wall: float
    rate: RateTracker


def load_expectations(base: dict[str, Any], robot: dict[str, Any] | None
                      ) -> tuple[list[DynamicEdgeSpec], list[tuple[str, str]]]:
    """`cr2-base.yaml` の `tf.dynamic` と、個体 yaml の `tf_static` を読む。"""
    dynamic = [
        DynamicEdgeSpec(parent=item['parent'], child=item['child'],
                        warn_sec=float(item['warn_sec']), crit_sec=float(item['crit_sec']),
                        source=item.get('source', ''))
        for item in ((base.get('tf') or {}).get('dynamic') or [])
    ]
    static = [(entry['parent'], child)
              for child, entry in ((robot or {}).get('tf_static') or {}).items()]
    return dynamic, static


class TfTree:
    """辺の保持と、配るフレームの組み立て。時刻はすべて引数で受け取る。"""

    def __init__(self, dynamic: list[DynamicEdgeSpec] | None = None,
                 static: list[tuple[str, str]] | None = None) -> None:
        self._dynamic = {spec.child: spec for spec in (dynamic or [])}
        self._expected_static = list(static or [])
        # tf では子に親は 1 つ。子をキーにする。
        self._edges: dict[str, _Edge] = {}

    def observe(self, parent: str, child: str, *, static: bool, wall_sec: float) -> None:
        edge = self._edges.get(child)
        if edge is None or edge.parent != parent:
            edge = _Edge(parent=parent, child=child, static=static,
                         last_wall=wall_sec, rate=RateTracker())
            self._edges[child] = edge
        # 一度でも /tf_static で届いたら静的。/tf でも同じ辺を出すノードがあっても、
        # 更新されないのが正常な辺として扱う。
        edge.static = edge.static or static
        edge.last_wall = wall_sec
        edge.rate.observe(wall_sec)

    @property
    def is_empty(self) -> bool:
        return not self._edges

    @property
    def expects_anything(self) -> bool:
        """期待の辺があるか。あれば 1 本も来ていなくても「無い」を配る。"""
        return bool(self._dynamic or self._expected_static)

    # ---- 判定 --------------------------------------------------------------

    def _edge_entry(self, edge: _Edge, wall_sec: float) -> dict[str, Any]:
        spec = self._dynamic.get(edge.child)
        expected = spec is not None and spec.parent == edge.parent
        entry: dict[str, Any] = {
            'parent': edge.parent,
            'child': edge.child,
            'static': edge.static,
            'expected': expected or (edge.parent, edge.child) in self._expected_static,
            'source': spec.source if expected else '',
        }
        if edge.static:
            entry.update(age=None, rate_hz=None, level=LEVEL_STATIC)
            return entry

        age = max(0.0, wall_sec - edge.last_wall)
        rate = edge.rate.rate(wall_sec)
        if not expected:
            level = LEVEL_UNJUDGED
        elif age >= spec.crit_sec:
            level = LEVEL_CRIT
        elif age >= spec.warn_sec:
            level = LEVEL_WARN
        else:
            level = LEVEL_OK
        entry.update(age=round(age, 2),
                     # 止まっているあいだは直前のレートを出さない（「停止中 30 Hz」は矛盾）
                     rate_hz=None if level in (LEVEL_WARN, LEVEL_CRIT) or rate is None
                     else round(rate, 1),
                     level=level)
        return entry

    def _missing(self) -> list[dict[str, Any]]:
        wanted = [(spec.parent, spec.child, 'dynamic', spec.source)
                  for spec in self._dynamic.values()]
        wanted += [(parent, child, 'static', '') for parent, child in self._expected_static]
        missing = []
        for parent, child, kind, source in wanted:
            edge = self._edges.get(child)
            if edge is not None and edge.parent == parent:
                continue
            missing.append({
                'parent': parent,
                'child': child,
                'kind': kind,
                'source': source,
                # 子は来ているが親が違う。宣言と実機の食い違い。
                'actual_parent': edge.parent if edge is not None else None,
            })
        return missing

    def frame(self, wall_sec: float) -> dict[str, Any]:
        edges = [self._edge_entry(edge, wall_sec) for edge in self._edges.values()]
        children = {edge.child for edge in self._edges.values()}
        parents = {edge.parent for edge in self._edges.values()}
        # 親として現れるが子として現れないフレーム = 木の根。
        # 2 つ以上なら木が分かれている（Nav2 が「not part of the same tree」で止まる状態）。
        roots = sorted(parents - children)
        return {
            'type': protocol.MSG_TF,
            # 以前の形（child -> parent）も残す。
            'parents': {edge.child: edge.parent for edge in self._edges.values()},
            'edges': sorted(edges, key=lambda e: (e['parent'], e['child'])),
            'roots': roots,
            'missing': self._missing(),
            'stamp': wall_sec,
        }
