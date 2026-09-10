"""stackd への薄いクライアント。

gateway の `tap` と同じ考え方で、uv 側の websockets を使う。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable


class StackdError(Exception):
    """接続または認証に失敗した。"""


async def run_command(url: str, token: str, request: dict | None, *,
                      follow: float = 0.0,
                      on_frame: Callable[[dict], None] | None = None) -> None:
    """1 コマンド送り、`follow` 秒だけ応答を受け続ける。

    `follow` を長めに取るのは、起動の様子（Nav2 の lifecycle が上がるまで）を
    見たいから。黙って戻ると「起動したのかどうか分からない」ことになる。
    """
    import websockets

    try:
        connection = await asyncio.wait_for(websockets.connect(url), 10)
    except Exception as exc:
        raise StackdError(
            f'stackd に接続できない ({url}): {exc}\n'
            '  起動していないなら: uv run whill-stackd') from exc

    async with connection as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if hello.get('service') != 'whill_stackd':
            raise StackdError(f'stackd ではない相手に繋がった: {hello}')

        await ws.send(json.dumps({'type': 'auth', 'token': token}))
        if request:
            await ws.send(json.dumps(request))

        loop = asyncio.get_running_loop()
        # コマンドの直後の応答は必ず拾う。follow=0 でも少しは待つ。
        deadline = loop.time() + max(follow, 1.5)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                raw = await asyncio.wait_for(ws.recv(), remaining)
            except asyncio.TimeoutError:
                return
            except Exception:
                return
            frame = json.loads(raw)
            if frame.get('type') == 'error' and frame.get('fatal'):
                raise StackdError(frame.get('reason', '拒否された'))
            if on_frame:
                on_frame(frame)
