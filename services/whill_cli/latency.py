"""スライダー → Nav2 反映の所要時間を測る。

Phase 3 の受け入れ条件「200 ms 以内」を、目分量ではなく数字で確かめる。

**1 つの数字にしない。** 「200 ms を超えた」だけ分かっても、ネットワークが
遅いのか gateway の検査が重いのか Nav2 が返さないのか区別できず、どこを
直せばよいか分からない。内訳を出す。

    total     クライアントの時計で測った往復（送信 → 結果の受信）
    gateway   gateway が受けてから結果を返すまで（gateway の時計）
    validate  registry の型・範囲・safety_class の検査
    service   ROS の SetParameters（= Nav2 の応答）
    network   total - gateway（= 往復のうち gateway の外）

時計合わせは要らない。total はクライアントの時計だけ、gateway 内の内訳は
gateway の時計だけで完結しており、`network` は同じ時計同士の差の引き算。
"""

from __future__ import annotations

import asyncio
import json
import statistics
from dataclasses import dataclass
from typing import Any

from whill_cli.tap import TapError
from whill_stackd import tls


@dataclass
class Sample:
    key: str
    accepted: bool
    total_ms: float
    gateway_ms: float
    validate_ms: float
    service_ms: float
    reason: str = ''

    @property
    def network_ms(self) -> float:
        # 負にならないよう下限を 0 にする。gateway とクライアントで
        # 計測の粒度が違うので、極小の往復では誤差で負に振れる。
        return max(0.0, self.total_ms - self.gateway_ms)


async def measure(url: str, token: str, keys: list[tuple[str, Any]], *,
                  repeats: int = 10) -> list[Sample]:
    """各キーを `repeats` 回変更し、所要時間を集める。

    同じ値を送り続けると Nav2 側が早期に返す可能性があるので、毎回
    わずかに違う値を送る。
    """
    import websockets

    try:
        connection = await asyncio.wait_for(websockets.connect(url, **tls.connect_kwargs(url)), 10)
    except Exception as exc:
        raise TapError(f'接続できない: {exc}') from exc

    samples: list[Sample] = []
    async with connection as ws:
        await ws.recv()
        await ws.send(json.dumps({'type': 'auth', 'token': token}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if reply.get('type') == 'error':
            raise TapError(f'認証に失敗した: {reply.get("reason")}')

        loop = asyncio.get_running_loop()
        for key, base in keys:
            for index in range(repeats):
                value = _vary(base, index)
                sent_at = loop.time() * 1000.0
                await ws.send(json.dumps({
                    'type': 'param_set', 'key': key, 'value': value,
                    'sent_at': sent_at,
                }))

                # 自分が投げた param_changed が返るまで読み飛ばす。
                # テレメトリが同じ接続に流れてくるため。
                while True:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if frame.get('type') == 'param_changed' and frame.get('key') == key:
                        break
                    if frame.get('type') == 'error':
                        raise TapError(str(frame.get('reason')))

                total = loop.time() * 1000.0 - sent_at
                timing = frame.get('timing') or {}
                samples.append(Sample(
                    key=key,
                    accepted=bool(frame.get('accepted')),
                    total_ms=total,
                    gateway_ms=float(timing.get('gateway_ms', 0.0)),
                    validate_ms=float(timing.get('validate_ms', 0.0)),
                    service_ms=float(timing.get('service_ms', 0.0)),
                    reason=str(frame.get('reason', '')),
                ))
    return samples


def _vary(base: Any, index: int) -> Any:
    """毎回わずかに違う値にする。同じ値だと早期に返される可能性がある。"""
    if isinstance(base, (int, float)) and not isinstance(base, bool):
        return round(float(base) + (index % 5) * 0.01, 4)
    return base


def summarize(samples: list[Sample]) -> dict[str, dict[str, float]]:
    """キーごとの中央値・最大値。

    平均ではなく中央値と最大を見る。平均は 1 回の外れ値で歪むし、
    受け入れ条件として意味があるのは「最悪でも 200 ms か」のほう。
    """
    out: dict[str, dict[str, float]] = {}
    by_key: dict[str, list[Sample]] = {}
    for sample in samples:
        by_key.setdefault(sample.key, []).append(sample)

    for key, group in by_key.items():
        out[key] = {
            'n': len(group),
            'total_median': statistics.median(s.total_ms for s in group),
            'total_max': max(s.total_ms for s in group),
            'gateway_median': statistics.median(s.gateway_ms for s in group),
            'validate_median': statistics.median(s.validate_ms for s in group),
            'service_median': statistics.median(s.service_ms for s in group),
            'network_median': statistics.median(s.network_ms for s in group),
        }
    return out
