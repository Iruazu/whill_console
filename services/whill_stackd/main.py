"""whill_stackd の入口。

実機PC に ssh せずに、他PC・tablet からスタックを起動・停止できるようにする
常駐サービス。`whill run` を子プロセスとして管理し、ログを WebSocket で流す。

gateway と同じ固定トークンを使う（`WHILL_GATEWAY_TOKEN`）。**未設定では
起動しない。** 起動・停止の口を無認証で開けるのは、テレメトリを配るより
危ない（誰でもスタックを落とせる）。

systemd ユニットは `whill-stackd.service` にある。**enable は実機復帰後。**
実機なしで enable すると「動いているつもり」になる。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from whill_stackd.server import DEFAULT_PORT, StackdServer


def _repo_root() -> str:
    env = os.environ.get('WHILL_PLATFORM_ROOT')
    if env:
        return env
    for parent in Path(__file__).resolve().parents:
        if (parent / 'config' / 'params.yaml').is_file():
            return str(parent)
    raise SystemExit(
        'リポジトリ根を見つけられない。WHILL_PLATFORM_ROOT を設定するか '
        'scripts/env.sh を source すること')


async def _run(host: str, port: int, token: str, repo_root: str) -> int:
    server = StackdServer(token=token, repo_root=repo_root)
    await server.serve(host, port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    # 自分が落ちるときは子も片付ける。孤児を残すと次の起動と喧嘩する。
    logging.getLogger('whill_stackd').info('終了する。子プロセスを停止する')
    await server.supervisor.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='whill-stackd',
        description='whill run を管理する常駐サービス')
    parser.add_argument('--host', default='0.0.0.0',
                        help='LAN 限定で使う前提。外向きに晒さないこと')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    token = os.environ.get('WHILL_GATEWAY_TOKEN', '')
    if not token:
        print('WHILL_GATEWAY_TOKEN が未設定。stackd は無認証では起動しない。\n'
              '  例: export WHILL_GATEWAY_TOKEN=$(openssl rand -hex 16)',
              file=sys.stderr)
        return 2
    if len(token) < 8:
        print('WHILL_GATEWAY_TOKEN が短すぎる（8 文字以上にすること）', file=sys.stderr)
        return 2

    return asyncio.run(_run(args.host, args.port, token, _repo_root()))


if __name__ == '__main__':
    raise SystemExit(main())
