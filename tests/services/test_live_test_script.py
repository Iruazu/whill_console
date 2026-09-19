"""`scripts/live-test.sh` の形（live テストを実際に回すための入口）。

live テストは gateway が要るので既定で skip され、CI でも走らない。
**走らせる手順が長いと、書いたきり誰も走らせないテストになる。** 入口を 1 本に
したので、その入口が腐らないように最低限を機械的に見る。

スクリプトそのものの動作確認は「実際に走らせる」こと（2 分）。ここで見るのは:

  1. **live のテストを 1 本も取りこぼしていない**（新しく足したら気づく）
  2. 動いているスタックを止めない作りであること
  3. 平文で上げること（ブラウザは ws:// で繋ぐ）
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'live-test.sh'
SPEC_DIR = ROOT / 'web' / 'tests'


def live_specs() -> set[str]:
    return {path.name for path in SPEC_DIR.glob('live*.spec.ts')}


def test_script_is_executable():
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK), 'chmod +x されていない'


def test_every_live_spec_is_run():
    """live のテストを足したのに入口に入れ忘れる、を防ぐ。"""
    text = SCRIPT.read_text('utf-8')
    referenced = set(re.findall(r'tests/(live[\w.-]*\.spec\.ts)', text))
    missing = live_specs() - referenced
    assert missing == set(), f'live-test.sh が走らせていない: {sorted(missing)}'


def test_every_live_spec_is_skipped_by_default():
    """既定で skip されること。CI で「gateway が無いから赤」にしない。"""
    for name in live_specs():
        text = (SPEC_DIR / name).read_text('utf-8')
        assert 'WHILL_LIVE' in text, name
        assert 'test.skip' in text, name


def test_it_refuses_to_touch_a_running_stack():
    """8765 が塞がっていたら諦める。**人が使っている最中かもしれない。**"""
    text = SCRIPT.read_text('utf-8')
    assert 'port ${PORT} が塞がっている' in text
    assert 'exit 1' in text


def test_it_runs_plaintext():
    """Playwright の開発サーバは http。gateway が wss だとブラウザから繋がらない。"""
    assert 'export WHILL_TLS=off' in SCRIPT.read_text('utf-8')


def test_it_cleans_up_what_it_started():
    text = SCRIPT.read_text('utf-8')
    assert 'trap stop_stack EXIT' in text
    # 終了時に port が空いていることまで確かめる（残すと次の実行が別のスタックに当たる）
    assert 'がまだ塞がっている' in text


def test_it_waits_until_nav2_is_active():
    """Nav2 が上がる前に配車のテストを始めると落ちる（実際に落ちた）。"""
    text = SCRIPT.read_text('utf-8')
    assert 'nav=active' in text


def test_it_does_not_pipe_into_grep_q_under_pipefail():
    """`grep -q` が先に終了すると SIGPIPE で相手が落ち、pipefail で失敗になる。

    これで「Nav2 が上がらない」と誤判定した。同じ形を持ち込まない。
    """
    text = SCRIPT.read_text('utf-8')
    assert not re.search(r'\|\s*grep -q', text), 'grep -q へのパイプが復活している'
