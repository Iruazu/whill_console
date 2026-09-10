"""gateway に繋いでフレームを覗く。

Phase 2 の受け入れ条件「別PC のブラウザから接続し、costmap と pose が JSON で
届く」を、ブラウザを開かずに機械的に確かめるための道具。UI のバグと gateway の
バグを切り分けるときにも使う。

クライアントは uv 側の `websockets`（新しい版）を使う。gateway 側が aiohttp
なのは ROS の python 環境が apt に縛られるためで（ADR-0003）、CLI 側には
その制約が無い。
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Any


class TapError(Exception):
    """接続または認証に失敗した。"""


async def tap(url: str, token: str, *, seconds: float,
              streams: list[str] | None = None,
              on_frame=None) -> Counter:
    """`seconds` 秒つないでフレームを数える。

    戻り値は type ごとの受信数。`on_frame` を渡すと 1 通ごとに呼ばれる。
    """
    import websockets

    counts: Counter = Counter()
    try:
        connection = await asyncio.wait_for(websockets.connect(url), 10)
    # ライブラリの例外型に依存しない。接続失敗の理由は文字列で伝える。
    except Exception as exc:
        raise TapError(f'接続できない: {exc}') from exc

    async with connection as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if hello.get('type') != 'hello':
            raise TapError(f'最初のフレームが hello でない: {hello.get("type")}')

        await ws.send(json.dumps({'type': 'auth', 'token': token}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if reply.get('type') == 'error':
            raise TapError(f'認証に失敗した: {reply.get("reason")}')
        if not reply.get('authenticated'):
            raise TapError('認証されなかった')

        if streams:
            await ws.send(json.dumps({'type': 'subscribe', 'streams': streams}))

        deadline = asyncio.get_running_loop().time() + seconds
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), remaining)
            except asyncio.TimeoutError:
                break
            # 切断は正常終了として扱う（tap は覗くだけの道具）
            except Exception:
                break
            frame = json.loads(raw)
            counts[frame.get('type', '?')] += 1
            if on_frame:
                on_frame(frame)

    return counts


def summarize(frame: dict[str, Any]) -> str:
    """1 行の要約。中身を全部出すと costmap で画面が埋まる。"""
    kind = frame.get('type')
    if kind == 'costmap':
        return (f"costmap  scope={frame['scope']} {frame['width']}x{frame['height']} "
                f"res={frame['resolution']:.3f} ratio={frame['ratio']:.4f} "
                f"seq={frame['seq']}")
    if kind == 'costmap_update':
        return (f"update   scope={frame['scope']} "
                f"({frame['x']},{frame['y']}) {frame['width']}x{frame['height']} "
                f"seq={frame['seq']}")
    if kind == 'pose':
        return (f"pose     {frame['source']} x={frame['x']:.2f} y={frame['y']:.2f} "
                f"yaw={frame['yaw']:.2f}")
    if kind == 'path':
        return f"path     {len(frame['points'])} 点"
    if kind == 'status':
        return (f"status   mode={frame['mode']} clients={frame['clients']} "
                f"estop={frame['estop']} nav={frame['nav_active']}")
    if kind == 'tf':
        return f"tf       {len(frame['parents'])} フレーム"
    if kind == 'diagnostics':
        return f"diag     {len(frame['entries'])} 件"
    if kind == 'image':
        return f"image    {frame['format']} {len(frame['data'])} B (base64)"
    if kind == 'error':
        return f"error    {frame['reason']}"
    return str(kind)
