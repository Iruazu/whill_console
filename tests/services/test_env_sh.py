"""`source scripts/env.sh` だけで `whill` が使えること。

実際に「`whill: コマンドが見つかりません`」でつまずいた（2026-09-14、自分で起動する
手順を初めて実践したとき）。`whill` は uv の環境（services/.venv）の中にあり、
PATH に入っていなかった。

venv の bin をそのまま PATH に足すと、venv の python3 がシステムの python3 を隠し、
ROS（rclpy）が import できなくなる。薄い入口（scripts/bin）だけを足していることも見る。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _in_fresh_shell(command: str, *, with_uv: bool = False) -> subprocess.CompletedProcess:
    # 呼び出し元の PATH の影響を受けないよう、最小の環境で bash を起動する。
    # uv の置き場所は環境しだい（手元は ~/.local/bin、CI は別の場所）なので、
    # 実際に動かすテストだけ uv のディレクトリを足す。
    path = '/usr/local/bin:/usr/bin:/bin'
    uv = shutil.which('uv')
    if with_uv and uv:
        path = f'{Path(uv).parent}:{path}'
    env = {'HOME': str(Path.home()), 'PATH': path}
    return subprocess.run(
        ['bash', '-c', f'set +u; source "{ROOT}/scripts/env.sh" >/dev/null 2>&1; {command}'],
        env=env, capture_output=True, text=True, timeout=120)


def test_whill_is_on_path_after_sourcing():
    result = _in_fresh_shell('command -v whill && command -v whill-stackd')
    assert result.returncode == 0, result.stderr
    lines = result.stdout.split()
    assert lines[0] == str(ROOT / 'scripts' / 'bin' / 'whill')
    assert lines[1] == str(ROOT / 'scripts' / 'bin' / 'whill-stackd')


def test_system_python_is_not_shadowed_by_the_venv():
    """venv の python3 が前に来ると、ROS の rclpy が import できなくなる。"""
    result = _in_fresh_shell('command -v python3')
    assert result.returncode == 0
    assert '.venv' not in result.stdout


@pytest.mark.skipif(shutil.which('uv') is None, reason='uv が無い環境')
def test_whill_actually_runs():
    result = _in_fresh_shell('whill --help', with_uv=True)
    assert result.returncode == 0, result.stderr
    assert 'run' in result.stdout


def test_missing_uv_is_explained(tmp_path):
    """uv が無いとき、何をすればよいかを言う。"""
    env = {'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin'}
    result = subprocess.run([str(ROOT / 'scripts' / 'bin' / 'whill'), '--help'],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 127
    assert 'uv が見つからない' in result.stderr


def test_whill_tls_off_clears_values_already_in_the_environment():
    """`WHILL_TLS=off` が、既に入っている TLS の変数も消すこと。

    消さないと「平文で上げたつもりの gateway が wss で待ち受ける」。同じシェルで
    先に（off 無しで）source していると起きる。live テストで実際に踏んだ:
    ブラウザは ws:// で繋ぐので、接続できずに 5 件まとめて落ちた。
    """
    script = (
        'export WHILL_TLS_CERT=/tmp/x.crt WHILL_TLS_KEY=/tmp/x.key WHILL_TLS_CA=/tmp/ca.crt; '
        f'export WHILL_TLS=off; source {ROOT}/scripts/env.sh >/dev/null 2>&1; '
        'echo "[${WHILL_TLS_CERT}${WHILL_TLS_KEY}${WHILL_TLS_CA}]"'
    )
    result = _in_fresh_shell(script)
    assert '[]' in result.stdout, result.stdout
