"""gateway の wss と CA 証明書の配布（#55）。

stackd（uv 側）の同じ規則は `tests/services/test_tls.py` が見ている。ここは
gateway（aiohttp）で実際に TLS で待ち受け、研究室 CA で検証して繋がることを
確かめる。証明書は `scripts/tls/` で毎回作る。
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
from pathlib import Path

import pytest

from whill_gateway import tls
from whill_gateway.server import CA_CERT_ROUTE, GatewayServer

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts' / 'tls'
TOKEN = 'tls-test-token-123'


@pytest.fixture(scope='module')
def tls_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp('gw-tls') / 'lab'
    env = {**os.environ, 'WHILL_TLS_DIR': str(directory)}
    for script in ('make-ca.sh', 'make-server-cert.sh'):
        subprocess.run([str(SCRIPTS / script)], env=env, check=True, capture_output=True)
    return directory


def _server_env(tls_dir: Path) -> dict[str, str]:
    return {'WHILL_TLS_CERT': str(tls_dir / 'server.crt'),
            'WHILL_TLS_KEY': str(tls_dir / 'server.key')}


# ---- 設定の規則 -------------------------------------------------------------


def test_unset_means_plaintext():
    assert tls.server_context({}) is None
    assert tls.scheme(None) == 'ws'


def test_half_configured_refuses_to_start(tls_dir):
    """黙って平文に戻ると「https のつもりで http」になり、iPad から原因が見えない。"""
    with pytest.raises(tls.TlsConfigError):
        tls.server_context({'WHILL_TLS_CERT': str(tls_dir / 'server.crt')})


def test_unreadable_files_refuse_to_start(tmp_path):
    with pytest.raises(tls.TlsConfigError, match='見つからない'):
        tls.server_context({'WHILL_TLS_CERT': str(tmp_path / 'x.crt'),
                            'WHILL_TLS_KEY': str(tmp_path / 'x.key')})


def test_valid_pair_gives_wss(tls_dir):
    context = tls.server_context(_server_env(tls_dir))
    assert isinstance(context, ssl.SSLContext)
    assert tls.scheme(context) == 'wss'


# ---- 実際に待ち受ける -------------------------------------------------------


async def _start(tls_dir: Path, ca_path: str | None):
    server = GatewayServer(token=TOKEN, robot_id='cr2-01', mode='mock')
    runner = await server.serve('127.0.0.1', 0,
                                ssl_context=tls.server_context(_server_env(tls_dir)),
                                ca_cert_path=ca_path)
    port = runner.addresses[0][1]
    return server, runner, port


@pytest.mark.asyncio
async def test_wss_handshake_and_hello_with_the_lab_ca(tls_dir):
    import aiohttp

    server, runner, port = await _start(tls_dir, None)
    client_ctx = ssl.create_default_context(cafile=str(tls_dir / 'ca.crt'))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f'wss://127.0.0.1:{port}/', ssl=client_ctx) as ws:
                hello = json.loads((await ws.receive(timeout=5)).data)
                assert hello['type'] == 'hello'
                assert hello['robot_id'] == 'cr2-01'
    finally:
        await server.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_client_without_the_lab_ca_cannot_connect(tls_dir):
    """検証を切っていない。研究室 CA を持たない相手は証明書を信頼しない。"""
    import aiohttp

    server, runner, port = await _start(tls_dir, None)
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientConnectorCertificateError):
                await session.ws_connect(f'wss://127.0.0.1:{port}/')
    finally:
        await server.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ca_certificate_is_served_for_ipad(tls_dir):
    """iPad に CA を渡す口。iOS がプロファイルとして扱う Content-Type で返す。"""
    import aiohttp

    server, runner, port = await _start(tls_dir, str(tls_dir / 'ca.crt'))
    client_ctx = ssl.create_default_context(cafile=str(tls_dir / 'ca.crt'))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://127.0.0.1:{port}{CA_CERT_ROUTE}',
                                   ssl=client_ctx) as response:
                assert response.status == 200
                assert response.content_type == 'application/x-x509-ca-cert'
                assert await response.read() == (tls_dir / 'ca.crt').read_bytes()
    finally:
        await server.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_a_private_key_is_never_served(tls_dir):
    """設定を取り違えて WHILL_TLS_CA が鍵を指していても、鍵は配らない。"""
    import aiohttp

    server, runner, port = await _start(tls_dir, str(tls_dir / 'ca.key'))
    client_ctx = ssl.create_default_context(cafile=str(tls_dir / 'ca.crt'))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://127.0.0.1:{port}{CA_CERT_ROUTE}',
                                   ssl=client_ctx) as response:
                body = await response.read()
                assert response.status == 500
                assert b'PRIVATE KEY' not in body
    finally:
        await server.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ca_route_does_not_exist_without_tls(tls_dir):
    """平文で待ち受けているときは配らない（iPad は平文の画面を開けないので意味が無い）。"""
    import aiohttp

    server = GatewayServer(token=TOKEN, robot_id='cr2-01', mode='mock')
    runner = await server.serve('127.0.0.1', 0, ssl_context=None,
                                ca_cert_path=str(tls_dir / 'ca.crt'))
    port = runner.addresses[0][1]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://127.0.0.1:{port}{CA_CERT_ROUTE}') as response:
                assert response.status == 404
    finally:
        await server.close()
        await runner.cleanup()
