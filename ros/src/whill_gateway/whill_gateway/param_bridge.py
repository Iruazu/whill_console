"""Web からのパラメータ操作を ROS に橋渡しする。

**registry を必ず通す。** WebSocket には任意の JSON を投げられるので、
UI 側の検査を信頼してはいけない（CLAUDE.md 設計原則 3、6）。

流れ:

    Web の param_set
      → registry.set_value() で型・範囲・safety_class を検査
      → 走行中なら locked_while_moving を拒否
      → registry.ros_node() が指す実ノードへ SetParameters
      → 受理・拒否の両方を /whill/param_changes に publish

拒否の記録も残すのは、「なぜ効かなかったのか」を後から追えるようにするため。
記録が受理だけだと、UI で動かしたのに変わらなかった原因が消える。

宛先ノード名に注意。Nav2 の costmap は yaml のキー（`local_costmap`）と
ROS のノード名（`/local_costmap/local_costmap`）が違う。Phase 1 で実測済み。
"""

from __future__ import annotations

import asyncio
from typing import Any

from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.node import Node

from whill_gateway import protocol
from whill_msgs.msg import ParamChange
from whill_params.registry import ParamSpec, Registry, RegistryError

SERVICE_TIMEOUT_SEC = 3.0
"""1 ノードへの set/get を待つ上限。

無限に待たない。Nav2 のノードが落ちているときに UI が固まるより、
「応答が無い」と返すほうがよい。
"""

MOVING_CMD_EPS = 0.02
"""この値を超える速度指令が出ていたら「走行中」とみなす。

厳密な停止判定ではない。`locked_while_moving` を効かせるための粗い門番で、
迷ったら「走行中」に倒す（変更を拒否する側に倒す）。
"""

MOVING_HOLD_SEC = 1.0
"""最後に速度指令を見てから、この時間は「走行中」を維持する。

`/cmd_vel` は停止時に publish が止まることがある。止まった瞬間を
「停止した」と解釈すると、惰性で動いている最中に変更を許してしまう。
"""


def _to_parameter_value(spec: ParamSpec, value: Any) -> ParameterValue:
    """registry の値を rcl_interfaces の型に載せ替える。"""
    pv = ParameterValue()
    if spec.type == 'bool':
        pv.type = ParameterType.PARAMETER_BOOL
        pv.bool_value = bool(value)
    elif spec.type == 'int':
        pv.type = ParameterType.PARAMETER_INTEGER
        pv.integer_value = int(value)
    elif spec.type == 'double':
        pv.type = ParameterType.PARAMETER_DOUBLE
        pv.double_value = float(value)
    elif spec.type == 'string':
        pv.type = ParameterType.PARAMETER_STRING
        pv.string_value = str(value)
    elif spec.type == 'double_array':
        pv.type = ParameterType.PARAMETER_DOUBLE_ARRAY
        pv.double_array_value = [float(v) for v in value]
    else:
        raise RegistryError(f'{spec.key}: 未対応の型 {spec.type}')
    return pv


def _from_parameter_value(pv: ParameterValue) -> Any:
    if pv.type == ParameterType.PARAMETER_BOOL:
        return pv.bool_value
    if pv.type == ParameterType.PARAMETER_INTEGER:
        return pv.integer_value
    if pv.type == ParameterType.PARAMETER_DOUBLE:
        return pv.double_value
    if pv.type == ParameterType.PARAMETER_STRING:
        return pv.string_value
    if pv.type == ParameterType.PARAMETER_DOUBLE_ARRAY:
        return list(pv.double_array_value)
    return None


def spec_payload(spec: ParamSpec, value: Any, ros_node: str) -> dict[str, Any]:
    """UI がスライダーを組むのに必要な情報。

    ここに載っていないものは UI に出ない。descriptor と同じ内容を
    WebSocket にも流すのは、ノードが起動する前から UI を組めるようにするため
    （ADR-0001）。
    """
    return {
        'key': spec.key,
        'node': spec.node,
        'ros_node': ros_node,
        'name': spec.name,
        'type': spec.type,
        'value': value,
        'default': spec.default,
        'range': spec.range,
        'elements': spec.elements,
        'unit': spec.unit,
        'live': spec.live,
        'safety_class': spec.safety_class,
        'description': spec.description,
    }


class MovingWatch:
    """`/cmd_vel` から「走行中か」を判定する。

    時刻は外から渡す。実時間を内部で読むとテストが不安定になる。
    """

    def __init__(self) -> None:
        self._last_moving: float | None = None

    def observe(self, vx: float, wz: float, now: float) -> None:
        if abs(vx) > MOVING_CMD_EPS or abs(wz) > MOVING_CMD_EPS:
            self._last_moving = now

    def is_moving(self, now: float) -> bool:
        if self._last_moving is None:
            return False
        return (now - self._last_moving) < MOVING_HOLD_SEC


class ParamBridge:
    """registry と ROS のパラメータサービスをつなぐ。"""

    def __init__(self, node: Node, registry: Registry, *,
                 loop_getter, moving_watch: MovingWatch) -> None:
        self.node = node
        self.registry = registry
        self._loop_getter = loop_getter
        self.moving = moving_watch
        self._clients: dict[str, dict[str, Any]] = {}
        self.change_pub = node.create_publisher(ParamChange, '/whill/param_changes', 10)

    # ---- ROS サービス ------------------------------------------------------

    def _client(self, ros_node: str, kind: str):
        """ノードごと・サービスごとにクライアントを使い回す。

        毎回作ると discovery のたびに待たされる。
        """
        srv_type, suffix = {
            'set': (SetParameters, 'set_parameters'),
            'get': (GetParameters, 'get_parameters'),
        }[kind]
        bucket = self._clients.setdefault(ros_node, {})
        if kind not in bucket:
            bucket[kind] = self.node.create_client(
                srv_type, f'{ros_node.rstrip("/")}/{suffix}')
        return bucket[kind]

    async def _call(self, client, request):
        """ROS のサービスを asyncio から待つ。

        rclpy の future は別スレッドの executor が完了させる。そのままでは
        await できないので、完了コールバックから asyncio の future へ
        `call_soon_threadsafe` で渡す。
        """
        if not client.service_is_ready():
            # discovery を少しだけ待つ。無ければ諦める（UI を固めない）。
            if not client.wait_for_service(timeout_sec=1.0):
                raise TimeoutError(f'{client.srv_name} が応答しない')

        loop = self._loop_getter()
        aio_future = loop.create_future()

        def _done(ros_future) -> None:
            def _set() -> None:
                if aio_future.done():
                    return
                try:
                    aio_future.set_result(ros_future.result())
                except Exception as exc:  # noqa: BLE001
                    aio_future.set_exception(exc)
            loop.call_soon_threadsafe(_set)

        client.call_async(request).add_done_callback(_done)
        return await asyncio.wait_for(aio_future, SERVICE_TIMEOUT_SEC)

    # ---- 配信 --------------------------------------------------------------

    async def params_frame(self) -> dict[str, Any]:
        """registry の全 spec と、実ノードの現在値を配る。

        registry の値ではなく**実ノードの値**を載せる。両者がずれていたら
        それ自体が異常なので、`mismatches` として明示する。UI が
        registry の値を表示して「設定したはずの値」を見せるのが一番危ない。
        """
        by_node: dict[str, list[ParamSpec]] = {}
        for spec in self.registry.specs.values():
            by_node.setdefault(self.registry.ros_node(spec.node), []).append(spec)

        params: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        unreachable: list[str] = []

        for ros_node, specs in sorted(by_node.items()):
            live: dict[str, Any] = {}
            try:
                request = GetParameters.Request()
                request.names = [s.name for s in specs]
                response = await self._call(self._client(ros_node, 'get'), request)
                for spec, pv in zip(specs, response.values, strict=False):
                    value = _from_parameter_value(pv)
                    if value is not None:
                        live[spec.name] = value
            # ノードが居ない / 応答しないのは想定内。例外型を細かく分けても
            # 扱いは同じ（registry の値で代替して先に進む）。
            except Exception:
                # ノードが居ないのは異常ではない（gateway だけ先に起動した等）。
                # 「読めなかった」ことを UI に伝え、registry の値で代替する。
                unreachable.append(ros_node)

            for spec in specs:
                value = live.get(spec.name, self.registry.values[spec.key])
                params.append(spec_payload(spec, value, ros_node))
                registry_value = self.registry.values[spec.key]
                if spec.name in live and not _close(value, registry_value):
                    mismatches.append({
                        'key': spec.key,
                        'registry': registry_value,
                        'live': value,
                    })

        return {
            'type': protocol.MSG_PARAMS,
            'params': params,
            'mismatches': mismatches,
            'unreachable': sorted(unreachable),
            'preset': self.registry.applied_preset,
            'presets': self._known_presets(),
        }

    def _known_presets(self) -> list[str]:
        from whill_params.registry import config_root
        try:
            return sorted(p.stem for p in (config_root() / 'presets').glob('*.yaml'))
        except Exception:  # noqa: BLE001 - preset が無くても致命ではない
            return []

    # ---- 変更 --------------------------------------------------------------

    async def set_value(self, key: str, value: Any, *, source: str) -> dict[str, Any]:
        """1 つのパラメータを変更する。結果のフレームを返す。

        検査に落ちた場合も例外にせず、拒否として記録して返す。UI は
        「なぜ拒否されたか」を出せる必要がある。
        """
        try:
            spec = self.registry.spec(key)
        except RegistryError as exc:
            self._log_change(None, '', '', source, False, str(exc))
            raise protocol.ProtocolError(str(exc)) from None

        old = self.registry.values[key]
        moving = self.moving.is_moving(self._now())

        try:
            self.registry.set_value(key, value, moving=moving)
        except RegistryError as exc:
            self._log_change(spec, old, value, source, False, str(exc))
            return {'type': protocol.MSG_PARAM_CHANGED, 'key': key,
                    'accepted': False, 'reason': str(exc), 'value': old}

        if not spec.live:
            # 再起動が要るものは ROS へ送らない。送っても効かないのに
            # 「成功」と返すと、UI が嘘をつくことになる。
            self._log_change(spec, old, value, source, False,
                             '再起動が必要（live: false）')
            self.registry.values[key] = old
            return {'type': protocol.MSG_PARAM_CHANGED, 'key': key,
                    'accepted': False, 'value': old,
                    'reason': 'このパラメータは再起動が必要（live: false）'}

        ros_node = self.registry.ros_node(spec.node)
        try:
            request = SetParameters.Request()
            parameter = Parameter()
            parameter.name = spec.name
            parameter.value = _to_parameter_value(spec, value)
            request.parameters = [parameter]
            response = await self._call(self._client(ros_node, 'set'), request)
        except Exception as exc:  # noqa: BLE001
            self.registry.values[key] = old
            reason = f'{ros_node} へ届かない: {exc}'
            self._log_change(spec, old, value, source, False, reason)
            return {'type': protocol.MSG_PARAM_CHANGED, 'key': key,
                    'accepted': False, 'reason': reason, 'value': old}

        result = response.results[0] if response.results else None
        if result is None or not result.successful:
            self.registry.values[key] = old
            reason = (result.reason if result and result.reason
                      else f'{ros_node} が拒否した')
            self._log_change(spec, old, value, source, False, reason)
            return {'type': protocol.MSG_PARAM_CHANGED, 'key': key,
                    'accepted': False, 'reason': reason, 'value': old}

        self._log_change(spec, old, value, source, True, '')
        return {'type': protocol.MSG_PARAM_CHANGED, 'key': key,
                'accepted': True, 'value': value, 'ros_node': ros_node}

    async def apply_preset(self, name: str, *, source: str) -> list[dict[str, Any]]:
        """preset の overrides をまとめて適用する。

        1 件でも失敗したら残りを止める、ということはしない。効いたものと
        効かなかったものを両方返し、UI に判断させる。途中で止めると
        「半分だけ適用された」状態が黙って残る。
        """
        from whill_params.registry import _load_yaml, config_root

        path = config_root() / 'presets' / f'{name}.yaml'
        try:
            preset = _load_yaml(path)
        except RegistryError as exc:
            raise protocol.ProtocolError(str(exc)) from None

        results = []
        for key, value in (preset.get('overrides') or {}).items():
            results.append(await self.set_value(key, value, source=f'preset:{name}'))
        if all(r['accepted'] for r in results):
            self.registry.applied_preset = name
        return results

    # ---- 記録 --------------------------------------------------------------

    def _log_change(self, spec: ParamSpec | None, old: Any, new: Any,
                    source: str, accepted: bool, reason: str) -> None:
        """受理も拒否も残す。

        拒否の記録が無いと、「UI で動かしたのに変わらなかった」原因が
        後から追えない。MCAP に載るので走行後の解析でも見られる。
        """
        msg = ParamChange()
        msg.header.stamp = self.node.get_clock().now().to_msg()
        msg.node = spec.node if spec else ''
        msg.name = spec.name if spec else ''
        msg.old_value = repr(old)
        msg.new_value = repr(new)
        msg.safety_class = spec.safety_class if spec else ''
        msg.source = source
        msg.accepted = accepted
        msg.reject_reason = reason
        self.change_pub.publish(msg)

    def _now(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1e9


def _close(a: Any, b: Any) -> bool:
    """registry の値と実ノードの値が実質同じか。

    bool と数値を混同しないこと。Python では `True == 1` が成り立つので、
    素朴に比較すると「bool のはずが int が入っている」という本物の
    食い違いを見逃す。mismatch を出すのが目的なので、型の違いは違いとして扱う。
    """
    if isinstance(a, list) != isinstance(b, list):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b
