"""gateway から Web 画面を配る（#56）。

見たいのは 3 つ:

  1. **同じ `/` で、アップグレード要求は WebSocket、それ以外は画面になる**
  2. **配る場所の外のファイルは絶対に返さない**（`..`、シンボリックリンク、符号化）
  3. **未ビルドでも gateway は動き、`/` で理由を言う**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whill_gateway import web_static
from whill_gateway.server import CA_CERT_ROUTE, GatewayServer

TOKEN = 'web-static-token-1'


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """`pnpm build` の成果物に似せた配置と、その外に置いた秘密のファイル。"""
    root = tmp_path / 'dist'
    (root / 'assets').mkdir(parents=True)
    (root / 'index.html').write_text('<!doctype html><title>whill</title>', 'utf-8')
    (root / 'assets' / 'index-abc123.js').write_text('console.log(1)', 'utf-8')
    (tmp_path / 'secret.txt').write_text('WHILL_GATEWAY_TOKEN=do-not-leak', 'utf-8')
    (root / 'escape').symlink_to(tmp_path / 'secret.txt')
    return root


# ---- 配る場所の決定 ---------------------------------------------------------


def test_explicit_web_root_wins(tmp_path):
    env = {'WHILL_WEB_ROOT': str(tmp_path / 'x'), 'WHILL_PLATFORM_ROOT': '/repo'}
    assert web_static.resolve_web_root(env) == tmp_path / 'x'


def test_platform_root_gives_web_dist():
    assert web_static.resolve_web_root({'WHILL_PLATFORM_ROOT': '/repo'}) == \
        Path('/repo/web/dist')


def test_nothing_set_means_no_web():
    assert web_static.resolve_web_root({}) is None
    assert web_static.is_built(None) is False


# ---- パスの検査 -------------------------------------------------------------


def test_root_path_is_index(site):
    assert web_static.safe_file(site, '/') == (site / 'index.html').resolve()


def test_asset_is_served(site):
    assert web_static.safe_file(site, '/assets/index-abc123.js') is not None


@pytest.mark.parametrize('path', [
    '/../secret.txt',
    '/assets/../../secret.txt',
    '/escape',                  # シンボリックリンクで外へ
    '/assets',                  # ディレクトリの一覧は見せない
    '/nope.js',
])
def test_nothing_outside_or_odd_is_returned(site, path):
    assert web_static.safe_file(site, path) is None


def test_index_is_revalidated_and_assets_are_cached(site):
    """index.html が残ると、ビルドし直したのに tablet だけ古い画面になる。"""
    assert web_static.cache_control(site, site / 'index.html') == 'no-cache'
    assert 'immutable' in web_static.cache_control(site, site / 'assets' / 'index-abc123.js')


# ---- 実際に待ち受ける -------------------------------------------------------


async def _start(web_root, *, ca_cert_path=None, ssl_context=None):
    server = GatewayServer(token=TOKEN, robot_id='cr2-01', mode='mock')
    runner = await server.serve('127.0.0.1', 0, web_root=web_root,
                                ca_cert_path=ca_cert_path, ssl_context=ssl_context)
    return server, runner, runner.addresses[0][1]


@pytest.mark.asyncio
async def test_same_root_serves_page_and_websocket(site):
    import aiohttp

    server, runner, port = await _start(site)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://127.0.0.1:{port}/') as page:
                assert page.status == 200
                assert page.content_type == 'text/html'
                assert page.headers['Cache-Control'] == 'no-cache'
                assert 'whill' in await page.text()

            # 同じ `/` へのアップグレード要求は WebSocket（CLI の接続先は変わらない）
            async with session.ws_connect(f'ws://127.0.0.1:{port}/') as ws:
                hello = json.loads((await ws.receive(timeout=5)).data)
                assert hello['type'] == 'hello'

            async with session.get(f'http://127.0.0.1:{port}/assets/index-abc123.js') as js:
                assert js.status == 200
                assert 'immutable' in js.headers['Cache-Control']
    finally:
        await server.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_encoded_traversal_does_not_leak(site):
    """ブラウザは `..` を畳むが、手で投げれば符号化したまま届く。"""
    import aiohttp
    from yarl import URL

    server, runner, port = await _start(site)
    try:
        async with aiohttp.ClientSession() as session:
            for raw in ('/%2e%2e/secret.txt', '/assets/%2e%2e/%2e%2e/secret.txt', '/escape'):
                url = URL(f'http://127.0.0.1:{port}{raw}', encoded=True)
                async with session.get(url) as response:
                    body = await response.text()
                    assert response.status == 404, raw
                    assert 'do-not-leak' not in body
    finally:
        await server.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_not_built_explains_and_keeps_websocket(tmp_path):
    """未ビルドでも gateway を止めない。止めると CLI や開発用の画面まで使えなくなる。"""
    import aiohttp

    server, runner, port = await _start(tmp_path / 'missing-dist')
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://127.0.0.1:{port}/') as page:
                text = await page.text()
                assert page.status == 503
                assert 'pnpm build' in text
                assert 'missing-dist' in text
            async with session.ws_connect(f'ws://127.0.0.1:{port}/') as ws:
                assert json.loads((await ws.receive(timeout=5)).data)['type'] == 'hello'
    finally:
        await server.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ca_certificate_route_still_wins_over_the_page(site, tmp_path):
    """画面のルートを足しても、iPad に CA を渡す口（#55）が隠れないこと。"""
    import os
    import ssl
    import subprocess

    import aiohttp

    from whill_gateway import tls

    scripts = Path(__file__).resolve().parents[2] / 'scripts' / 'tls'
    tls_dir = tmp_path / 'tls'
    env = {**os.environ, 'WHILL_TLS_DIR': str(tls_dir)}
    for script in ('make-ca.sh', 'make-server-cert.sh'):
        subprocess.run([str(scripts / script)], env=env, check=True, capture_output=True)

    server, runner, port = await _start(
        site, ca_cert_path=str(tls_dir / 'ca.crt'),
        ssl_context=tls.server_context({'WHILL_TLS_CERT': str(tls_dir / 'server.crt'),
                                        'WHILL_TLS_KEY': str(tls_dir / 'server.key')}))
    client = ssl.create_default_context(cafile=str(tls_dir / 'ca.crt'))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://127.0.0.1:{port}{CA_CERT_ROUTE}',
                                   ssl=client) as response:
                assert response.content_type == 'application/x-x509-ca-cert'
            async with session.get(f'https://127.0.0.1:{port}/', ssl=client) as page:
                assert page.status == 200
    finally:
        await server.close()
        await runner.cleanup()
