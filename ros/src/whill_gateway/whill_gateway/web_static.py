"""Web 画面（`pnpm build` の成果物）を gateway から配る（#56）。

**aiohttp にも rclpy にも依存しない部分**（配る場所の決定、パスの検査、
キャッシュの指定）をここに置く。HTTP の応答を組むのは `server.py`。

## なぜ gateway から配るか

これまでは開発用の Vite（5173）で画面を出していて、現場でも実機PC で
`pnpm dev` を起動していた。gateway から配ると:

- ブラウザは `https://<実機PC>:8765/` を開くだけになる。**画面と WebSocket が
  同じオリジン・同じポート・同じ証明書**になる
- 現場で Vite を起動しない。`whill run --gateway`（最終的には stackd の自動起動）
  だけで画面まで出る

## WebSocket と画面を同じ `/` で分ける

WebSocket を `/ws` に移さず、**`/` へのアップグレード要求かどうか**で振り分ける。
`whill tap` などの CLI や既存の接続先（`wss://<host>:8765`）を変えずに済むため。

## 配る場所

`WHILL_WEB_ROOT` があればそこ、無ければ `$WHILL_PLATFORM_ROOT/web/dist`
（`scripts/env.sh` と systemd ユニットが `WHILL_PLATFORM_ROOT` を設定する）。
パラメータ（`params.yaml`）に置かないのは、スライダーで変える値ではなく
その機体のファイル配置だから。証明書のパスと同じ扱い。

ビルド成果物は git に入れない（`web/dist/` は ignore 済み）。実機PC で
`cd web && pnpm build` する。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ENV_WEB_ROOT = 'WHILL_WEB_ROOT'
ENV_PLATFORM_ROOT = 'WHILL_PLATFORM_ROOT'

INDEX = 'index.html'

NOT_BUILT_HTML = """<!doctype html>
<meta charset="utf-8">
<title>whill_console: 画面が未ビルド</title>
<body style="font-family: system-ui, sans-serif; background:#14171c; color:#e6e9ee;
             max-width: 40em; margin: 12vh auto; padding: 0 16px; line-height: 1.7">
<h1 style="font-size: 18px">画面がまだビルドされていない</h1>
<p>gateway は動いている（WebSocket は使える）が、配る画面のファイルが無い。</p>
<p>実機PC で次を実行してから、このページを開き直すこと。</p>
<pre style="background:#1c2027; padding: 10px; border-radius: 4px">cd web &amp;&amp; pnpm build</pre>
<p style="color:#8b95a3">探した場所: <code>{root}</code></p>
</body>
"""
"""未ビルドのときに `/` で返すページ。

gateway を止めない。止めると WebSocket（CLI の `whill tap` や開発用 Vite の
画面）まで使えなくなる。**なぜ画面が出ないかをその場で言う。**
"""


def resolve_web_root(env: Mapping[str, str] | None = None) -> Path | None:
    """配る場所。決められなければ None（画面は配らない）。"""
    env = os.environ if env is None else env
    explicit = env.get(ENV_WEB_ROOT, '').strip()
    if explicit:
        return Path(explicit).expanduser()
    platform = env.get(ENV_PLATFORM_ROOT, '').strip()
    if platform:
        return Path(platform).expanduser() / 'web' / 'dist'
    return None


def is_built(root: Path | None) -> bool:
    return root is not None and (root / INDEX).is_file()


def safe_file(root: Path, request_path: str) -> Path | None:
    """リクエストのパスを、`root` の中の実在するファイルに解決する。

    **`root` の外は絶対に返さない。** `..` やシンボリックリンクで外に出る
    パスは None。ブラウザからは任意のパスを投げられる。

    ディレクトリや存在しないパスも None（一覧を見せない）。
    """
    relative = request_path.lstrip('/')
    if not relative:
        relative = INDEX
    try:
        base = root.resolve(strict=True)
        candidate = (base / relative).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def cache_control(root: Path, file: Path) -> str:
    """キャッシュの指定。

    `index.html` は毎回確かめさせる。古い画面がキャッシュに残ると、ビルドし直した
    のに tablet だけ前の画面、になる。`assets/` はファイル名にハッシュが付くので
    長く持たせてよい。
    """
    try:
        relative = file.resolve().relative_to(root.resolve())
    except ValueError:
        return 'no-store'
    if relative.parts and relative.parts[0] == 'assets':
        return 'public, max-age=31536000, immutable'
    return 'no-cache'
