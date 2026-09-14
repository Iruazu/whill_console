"""TLS の設定を環境変数から読む（#55）。stackd と CLI で共用する。

gateway にも同じ規則の実装がある（`ros/src/whill_gateway/whill_gateway/tls.py`）。
**片方だけ変えないこと。** uv 側と ROS 側は Python 環境が分かれているので
（設計原則 5）、同じ小さな関数を両方に置いている。

| 環境変数 | 使う側 | 意味 |
|---|---|---|
| `WHILL_TLS_CERT` / `WHILL_TLS_KEY` | 待ち受け（stackd） | 両方あれば TLS。片方だけ・読めないなら**起動しない** |
| `WHILL_TLS_CA` | 接続（CLI） | あれば `wss://` で繋ぎ、この CA で検証する |

**検証を切るオプションは作らない。** 一時しのぎのつもりで残り、LAN 内で
なりすましを通すことになる。
"""

from __future__ import annotations

import os
import ssl
from collections.abc import Mapping

ENV_CERT = 'WHILL_TLS_CERT'
ENV_KEY = 'WHILL_TLS_KEY'
ENV_CA = 'WHILL_TLS_CA'


class TlsConfigError(Exception):
    """TLS の指定が不完全か、証明書を読めない。"""


def server_context(env: Mapping[str, str] | None = None) -> ssl.SSLContext | None:
    """待ち受け用。未設定なら None（平文）。"""
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
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(certfile=cert, keyfile=key)
    except FileNotFoundError as exc:
        raise TlsConfigError(
            f'証明書か鍵が見つからない: {exc.filename}。'
            f'scripts/tls/make-server-cert.sh で発行すること') from exc
    except (ssl.SSLError, OSError) as exc:
        raise TlsConfigError(f'証明書か鍵を読めない（{cert}, {key}）: {exc}') from exc
    return context


def client_context(env: Mapping[str, str] | None = None) -> ssl.SSLContext | None:
    """接続用。`WHILL_TLS_CA` が無ければ None（平文の `ws://`）。"""
    env = os.environ if env is None else env
    ca = env.get(ENV_CA, '').strip()
    if not ca:
        return None
    try:
        return ssl.create_default_context(cafile=ca)
    except FileNotFoundError as exc:
        raise TlsConfigError(f'CA 証明書が見つからない: {ca}') from exc
    except (ssl.SSLError, OSError) as exc:
        raise TlsConfigError(f'CA 証明書を読めない（{ca}）: {exc}') from exc


def scheme(env: Mapping[str, str] | None = None) -> str:
    """CLI が組み立てる URL の scheme。CA が設定されていれば wss。"""
    env = os.environ if env is None else env
    return 'wss' if env.get(ENV_CA, '').strip() else 'ws'


def connect_kwargs(url: str, env: Mapping[str, str] | None = None) -> dict:
    """`websockets.connect(url, **kwargs)` に渡す追加引数。

    `wss://` なのに CA が無ければ、既定の信頼ストア（公開 CA）で検証される。
    研究室 CA の証明書はそこに無いので失敗する — 黙って検証を切るより、
    そのほうが原因が分かる。
    """
    if not url.startswith('wss://'):
        return {}
    context = client_context(env)
    return {'ssl': context} if context is not None else {}
