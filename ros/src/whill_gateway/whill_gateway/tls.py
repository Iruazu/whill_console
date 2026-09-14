"""TLS の設定を環境変数から読む（#55）。

**rclpy にも aiohttp にも依存しない。** 標準の `ssl` だけで組むので、ROS を
立てずに検証できる。stackd（uv 側）にも同じ規則の実装がある
（`services/whill_stackd/tls.py`）。**片方だけ変えないこと。**

## なぜ要るか

iPad の Safari / Chrome は `http://` を `https://` に上げてしまい、http の画面を
開けない（2026-09-14 に `ERR_SSL_PROTOCOL_ERROR` を実測）。https のページからは
平文の `ws://` にも繋げないので、gateway も `wss://` で待ち受ける必要がある。

## 規則

| `WHILL_TLS_CERT` / `WHILL_TLS_KEY` | 挙動 |
|---|---|
| どちらも未設定 | 平文（CI・開発用）。ログに平文であることを出す |
| 両方設定、読める | TLS で待ち受ける |
| 片方だけ、または読めない | **起動しない** |

**指定されているのに平文に戻らない。** 黙って戻ると「https のつもりで http」に
なり、iPad からは今回と同じエラーしか見えず原因が分からない。トークン未設定で
起動しないのと同じ考え方。
"""

from __future__ import annotations

import os
import ssl
from collections.abc import Mapping

ENV_CERT = 'WHILL_TLS_CERT'
ENV_KEY = 'WHILL_TLS_KEY'


class TlsConfigError(Exception):
    """TLS の指定が不完全か、証明書を読めない。"""


def server_context(env: Mapping[str, str] | None = None) -> ssl.SSLContext | None:
    """待ち受け用の SSLContext。未設定なら None（平文）。"""
    env = os.environ if env is None else env
    cert = env.get(ENV_CERT, '').strip()
    key = env.get(ENV_KEY, '').strip()

    if not cert and not key:
        return None
    if not cert or not key:
        missing = ENV_KEY if cert else ENV_CERT
        raise TlsConfigError(
            f'{missing} が未設定（{ENV_CERT} と {ENV_KEY} は両方指定すること）')

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    # iOS Safari が話せる範囲で古いものは切る。
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(certfile=cert, keyfile=key)
    except FileNotFoundError as exc:
        raise TlsConfigError(
            f'証明書か鍵が見つからない: {exc.filename}。'
            f'scripts/tls/make-server-cert.sh で発行すること') from exc
    except (ssl.SSLError, OSError) as exc:
        raise TlsConfigError(
            f'証明書か鍵を読めない（{cert}, {key}）: {exc}') from exc
    return context


def scheme(context: ssl.SSLContext | None) -> str:
    """ログと案内に出す URL の scheme。"""
    return 'wss' if context is not None else 'ws'
