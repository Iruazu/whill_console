"""研究室 CA と wss のテスト（#55）。

見たいのは 3 つ:

  1. **スクリプトが作る証明書を、クライアントが本当に信頼して繋がる。**
     `openssl verify` が通るだけでなく、wss のハンドシェイクが成立すること
  2. **CA の Name Constraints が効く。** 鍵が漏れても公開サイトの証明書は通らない
  3. **設定の誤りで平文に戻らない。** 片方だけ・読めないなら起動しない

証明書は `scripts/tls/` のスクリプトで毎回作る。スクリプトそのものも検証する。
"""

from __future__ import annotations

import asyncio
import os
import ssl
import subprocess
from pathlib import Path

import pytest

from whill_stackd import tls

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts' / 'tls'


@pytest.fixture(scope='module')
def tls_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp('tls') / 'lab'
    env = {**os.environ, 'WHILL_TLS_DIR': str(directory)}
    subprocess.run([str(SCRIPTS / 'make-ca.sh')], env=env, check=True,
                   capture_output=True)
    subprocess.run([str(SCRIPTS / 'make-server-cert.sh')], env=env, check=True,
                   capture_output=True)
    return directory


def _openssl(*args: str) -> str:
    return subprocess.run(['openssl', *args], check=True, capture_output=True,
                          text=True).stdout


# ---- スクリプトが作るもの ---------------------------------------------------


def test_server_cert_verifies_against_the_ca(tls_dir):
    out = _openssl('verify', '-CAfile', str(tls_dir / 'ca.crt'), str(tls_dir / 'server.crt'))
    assert out.strip().endswith('OK')


def test_keys_are_not_readable_by_others(tls_dir):
    """鍵は 600。CA の鍵が読めると、その iPad に対して何でも偽装できる。"""
    for name in ('ca.key', 'server.key'):
        assert (tls_dir / name).stat().st_mode & 0o077 == 0, name


def test_server_cert_meets_apple_requirements(tls_dir):
    """SAN 必須・EKU serverAuth・825 日以内（ここでは 397 日）。"""
    text = _openssl('x509', '-in', str(tls_dir / 'server.crt'), '-noout', '-text')
    assert 'TLS Web Server Authentication' in text
    assert 'Subject Alternative Name' in text
    assert 'DNS:localhost' in text
    assert 'IP Address:127.0.0.1' in text
    # iPhone テザリングの範囲と、以前のアクセスポイント
    assert 'IP Address:172.20.10.2' in text and 'IP Address:172.20.10.14' in text
    assert 'IP Address:10.42.0.1' in text

    def expires_within(days: int) -> bool:
        # -checkend は「その秒数のうちに切れる」ときに 1 で終わる。
        result = subprocess.run(
            ['openssl', 'x509', '-in', str(tls_dir / 'server.crt'), '-noout',
             '-checkend', str(days * 86400)], capture_output=True, text=True)
        return result.returncode == 1

    assert expires_within(825), 'Apple の上限（825 日）を超えている'
    assert not expires_within(390), '有効期間が短すぎる'


def test_ca_is_name_constrained(tls_dir):
    text = _openssl('x509', '-in', str(tls_dir / 'ca.crt'), '-noout', '-text')
    assert 'Name Constraints: critical' in text
    assert 'DNS:local' in text
    assert 'IP:192.168.0.0/255.255.0.0' in text


def test_ca_is_not_overwritten(tls_dir):
    """上書きすると、信頼させた iPad すべてで設定をやり直すことになる。"""
    before = (tls_dir / 'ca.crt').read_bytes()
    result = subprocess.run([str(SCRIPTS / 'make-ca.sh')],
                            env={**os.environ, 'WHILL_TLS_DIR': str(tls_dir)},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert (tls_dir / 'ca.crt').read_bytes() == before


def test_a_public_name_signed_by_the_ca_is_rejected(tls_dir, tmp_path):
    """CA の鍵が漏れても、公開サイトの証明書は検証で落ちる（Name Constraints）。"""
    key, csr, crt, ext = (tmp_path / n for n in ('evil.key', 'evil.csr', 'evil.crt', 'ext'))
    _openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
             '-subj', '/CN=example.com', '-out', str(csr))
    ext.write_text('subjectAltName=DNS:example.com\nextendedKeyUsage=serverAuth\n')
    _openssl('x509', '-req', '-in', str(csr), '-CA', str(tls_dir / 'ca.crt'),
             '-CAkey', str(tls_dir / 'ca.key'), '-CAcreateserial', '-days', '30',
             '-extfile', str(ext), '-out', str(crt))
    result = subprocess.run(['openssl', 'verify', '-CAfile', str(tls_dir / 'ca.crt'), str(crt)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'subtree violation' in (result.stdout + result.stderr)


def test_public_address_is_refused_by_the_script(tls_dir):
    """制約の外のアドレスは入れても iPad が拒否する。入れる前に止める。"""
    result = subprocess.run([str(SCRIPTS / 'make-server-cert.sh'), '8.8.8.8'],
                            env={**os.environ, 'WHILL_TLS_DIR': str(tls_dir)},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'LAN 内のアドレスではない' in result.stderr


# ---- 設定の読み取り ---------------------------------------------------------


def test_nothing_set_means_plaintext():
    assert tls.server_context({}) is None
    assert tls.client_context({}) is None
    assert tls.scheme({}) == 'ws'


def test_only_one_of_cert_and_key_refuses_to_start(tls_dir):
    """片方だけで平文に戻ると「https のつもりで http」になる。"""
    with pytest.raises(tls.TlsConfigError, match='WHILL_TLS_KEY'):
        tls.server_context({'WHILL_TLS_CERT': str(tls_dir / 'server.crt')})
    with pytest.raises(tls.TlsConfigError, match='WHILL_TLS_CERT'):
        tls.server_context({'WHILL_TLS_KEY': str(tls_dir / 'server.key')})


def test_missing_files_refuse_to_start(tmp_path):
    with pytest.raises(tls.TlsConfigError, match='見つからない'):
        tls.server_context({'WHILL_TLS_CERT': str(tmp_path / 'nope.crt'),
                            'WHILL_TLS_KEY': str(tmp_path / 'nope.key')})


def test_mismatched_cert_and_key_refuse_to_start(tls_dir):
    with pytest.raises(tls.TlsConfigError, match='読めない'):
        tls.server_context({'WHILL_TLS_CERT': str(tls_dir / 'server.crt'),
                            'WHILL_TLS_KEY': str(tls_dir / 'ca.key')})


def test_ca_makes_the_cli_use_wss(tls_dir):
    env = {'WHILL_TLS_CA': str(tls_dir / 'ca.crt')}
    assert tls.scheme(env) == 'wss'
    assert 'ssl' in tls.connect_kwargs('wss://127.0.0.1:8770', env)
    assert tls.connect_kwargs('ws://127.0.0.1:8770', env) == {}


def test_gateway_and_stackd_share_the_same_rules():
    """uv 側と ROS 側で同じ規則の実装を 2 つ持っている。食い違いを見つける。"""
    gateway = (ROOT / 'ros' / 'src' / 'whill_gateway' / 'whill_gateway' / 'tls.py').read_text()
    for name in ("ENV_CERT = 'WHILL_TLS_CERT'", "ENV_KEY = 'WHILL_TLS_KEY'",
                 'TLSVersion.TLSv1_2', 'class TlsConfigError'):
        assert name in gateway, name


# ---- 実際のハンドシェイク ---------------------------------------------------


async def _echo_server(context: ssl.SSLContext | None):
    import websockets

    async def handler(ws):
        async for message in ws:
            await ws.send(message)

    return await websockets.serve(handler, '127.0.0.1', 0, ssl=context)


async def test_wss_handshake_with_the_lab_ca(tls_dir):
    import websockets

    server = await _echo_server(tls.server_context({
        'WHILL_TLS_CERT': str(tls_dir / 'server.crt'),
        'WHILL_TLS_KEY': str(tls_dir / 'server.key')}))
    port = server.sockets[0].getsockname()[1]
    url = f'wss://127.0.0.1:{port}'
    try:
        env = {'WHILL_TLS_CA': str(tls_dir / 'ca.crt')}
        async with websockets.connect(url, **tls.connect_kwargs(url, env)) as ws:
            await ws.send('ping')
            assert await asyncio.wait_for(ws.recv(), 5) == 'ping'
    finally:
        server.close()
        await server.wait_closed()


async def test_wss_without_the_lab_ca_is_rejected(tls_dir):
    """研究室 CA を持たないクライアントは、証明書を信頼しない（検証を切っていない）。"""
    import websockets

    server = await _echo_server(tls.server_context({
        'WHILL_TLS_CERT': str(tls_dir / 'server.crt'),
        'WHILL_TLS_KEY': str(tls_dir / 'server.key')}))
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            async with websockets.connect(f'wss://127.0.0.1:{port}'):
                pass
    finally:
        server.close()
        await server.wait_closed()
