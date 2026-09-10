"""registry の ParamSpec から rcl_interfaces の ParameterDescriptor を作る。

自作ノードは必ずこれを通してパラメータを宣言する（CLAUDE.md 設計原則 6）。
descriptor に範囲と説明が入っていないと、gateway の introspection が
スライダーを作れず UI に何も出ない。手で declare_parameter を書かないこと。
"""

from __future__ import annotations

from typing import Any

from rcl_interfaces.msg import (
    FloatingPointRange,
    IntegerRange,
    ParameterDescriptor,
)

from whill_params.registry import ParamSpec, Registry


def _description_text(spec: ParamSpec) -> str:
    """UI のツールチップに出る文字列。単位と live/safety を末尾に足す。"""
    tail = []
    if spec.unit:
        tail.append(f'unit={spec.unit}')
    tail.append('live' if spec.live else 'restart required')
    if spec.safety_class != 'none':
        tail.append(spec.safety_class)
    return f'{spec.description} [{", ".join(tail)}]'


def descriptor_for(spec: ParamSpec) -> ParameterDescriptor:
    """1 つの ParamSpec に対応する descriptor を作る。"""
    descriptor = ParameterDescriptor()
    descriptor.name = spec.name
    descriptor.description = _description_text(spec)
    # live=false は「再起動が要る」という意味であって読み取り専用ではない。
    # read_only にすると起動後の set が RCL レベルで弾かれ、再起動込みの
    # 適用フロー（stackd の restart）まで塞いでしまうので false のまま。
    descriptor.read_only = False

    if spec.range:
        lo, hi = spec.range.get('min'), spec.range.get('max')
        step = spec.range.get('step')
        if spec.type == 'int' and lo is not None and hi is not None:
            rng = IntegerRange()
            rng.from_value = int(lo)
            rng.to_value = int(hi)
            rng.step = int(step or 1)
            descriptor.integer_range = [rng]
        elif spec.type in ('double', 'double_array') and lo is not None and hi is not None:
            rng = FloatingPointRange()
            rng.from_value = float(lo)
            rng.to_value = float(hi)
            # double_array には rcl の範囲制約が効かないので、descriptor は
            # UI へのヒントとしてだけ載せ、実際の検査は registry 側で行う。
            rng.step = float(step or 0.0)
            descriptor.floating_point_range = [rng]

    return descriptor


def declare_from_registry(node: Any, registry: Registry, node_name: str | None = None) -> list[str]:
    """registry のうち指定ノードぶんを rclpy ノードへ一括宣言する。

    戻り値は宣言したパラメータ名のリスト。
    """
    target = node_name or node.get_name()
    declared: list[str] = []
    for spec in registry.specs.values():
        if spec.node != target:
            continue
        value = registry.values.get(spec.key, spec.default)
        node.declare_parameter(spec.name, value, descriptor_for(spec))
        declared.append(spec.name)
    return declared
