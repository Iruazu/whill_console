"""gateway が終わったら launch ごと失敗として止めるテスト（K11, #49）。

見たいのは 3 つ:

  1. **gateway が死んだら launch が非 0 で終わる。** 0 だと stackd が「停止」と
     表示し、「スタックは動いているのに誰も繋がらない」の原因を隠す
  2. **普通の停止（Ctrl-C / stackd の stop）は失敗にしない**
  3. **bag play には付けていない。** 再生が終わっても gateway は残す（ADR-0004）

1 と 2 は本物の `LaunchService` で確かめる。Humble の launch が「イベント処理中の
例外でしか非 0 を返さない」ことに依存しているので、launch の挙動が変わったら
ここで気づけるようにしてある。gateway の代わりに python の子プロセスを使う。
"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BRINGUP = ROOT / 'ros' / 'src' / 'whill_bringup'
sys.path.insert(0, str(BRINGUP))

from whill_bringup.gateway_guard import (  # noqa: E402
    GatewayExited,
    describe,
    on_gateway_exit,
)


# ---- ハンドラ単体 -----------------------------------------------------------


def test_exit_outside_shutdown_raises():
    with pytest.raises(GatewayExited, match='exit 1'):
        on_gateway_exit(SimpleNamespace(returncode=1), SimpleNamespace(is_shutdown=False))


def test_a_clean_exit_outside_shutdown_is_still_a_failure():
    """gateway は待ち受け続けるプロセス。自分から 0 で終わる場面が無い。"""
    with pytest.raises(GatewayExited, match='exit 0'):
        on_gateway_exit(SimpleNamespace(returncode=0), SimpleNamespace(is_shutdown=False))


def test_exit_during_shutdown_is_not_a_failure():
    """Ctrl-C や stackd の stop で gateway が終わるのは正常。"""
    assert on_gateway_exit(
        SimpleNamespace(returncode=-2), SimpleNamespace(is_shutdown=True)) is None


def test_reason_says_what_to_check():
    """「終了した」だけだと、現地で次に何を見ればよいか分からない。"""
    text = describe(1)
    assert '8765' in text
    assert 'WHILL_GATEWAY_TOKEN' in text


def test_unknown_returncode_is_described():
    assert '不明' in describe(None)


# ---- 本物の LaunchService ---------------------------------------------------


launch = pytest.importorskip('launch')


WATCHDOG_SEC = 20.0


def _run(actions) -> tuple[int, float]:
    """launch を走らせ、終了コードと所要時間を返す。

    **番犬を必ず付ける。** 守りが壊れると launch は自分では止まらず
    `run()` が永久に返らない — 失敗ではなく**テストが固まる**（実際に、
    ハンドラを無効にして確かめたときに固まった）。CI が固まるより、
    番犬が止めて「止まらなかった」と失敗させるほうがよい。
    """
    fired: list[bool] = []

    def _mark(_context):
        fired.append(True)
        return []

    watchdog = launch.actions.TimerAction(
        period=WATCHDOG_SEC,
        actions=[launch.actions.OpaqueFunction(function=_mark),
                 launch.actions.Shutdown(reason='test watchdog')])

    service = launch.LaunchService()
    service.include_launch_description(launch.LaunchDescription([*actions, watchdog]))
    start = time.monotonic()
    code = service.run()
    elapsed = time.monotonic() - start
    assert not fired, f'launch が自分で止まらず、番犬が {WATCHDOG_SEC:.0f} s で止めた'
    return code, elapsed


def _long_running(name: str):
    """Nav2 やドライバの代わり。SIGINT で素直に終わる。"""
    return launch.actions.ExecuteProcess(
        cmd=[sys.executable, '-c', 'import time\nwhile True: time.sleep(0.1)'],
        name=name, output='log', sigterm_timeout='2', sigkill_timeout='2')


def test_gateway_dying_takes_the_launch_down_with_a_nonzero_code():
    """8765 番の衝突やトークン未設定で gateway が起動直後に死ぬ場合。"""
    gateway = launch.actions.ExecuteProcess(
        cmd=[sys.executable, '-c', 'import sys, time; time.sleep(0.5); sys.exit(1)'],
        name='fake_gateway', output='log', on_exit=on_gateway_exit)

    code, elapsed = _run([_long_running('fake_nav2'), gateway])

    assert code != 0, '終了コードが 0 だと stackd が「停止」と表示して原因を隠す'
    # 残りのプロセスを待たずに止まっていること（SIGINT → 猶予のうちに終わる）。
    assert elapsed < 15


def test_plain_shutdown_alone_would_exit_zero():
    """`on_exit=Shutdown()` では足りないことの確認（この実装にした理由）。

    これが非 0 を返すようになったら、launch の挙動が変わったということ。
    そのときは gateway_guard を Shutdown に戻せるか見直すこと。
    """
    gateway = launch.actions.ExecuteProcess(
        cmd=[sys.executable, '-c', 'import sys, time; time.sleep(0.5); sys.exit(1)'],
        name='fake_gateway', output='log',
        on_exit=launch.actions.Shutdown(reason='gateway exited'))

    code, _ = _run([_long_running('fake_nav2'), gateway])
    assert code == 0


def test_normal_shutdown_is_not_reported_as_a_failure():
    """停止処理の中で gateway が終わっても、例外にしない。"""
    gateway = launch.actions.ExecuteProcess(
        cmd=[sys.executable, '-c', 'import time\nwhile True: time.sleep(0.1)'],
        name='fake_gateway', output='log', on_exit=on_gateway_exit,
        sigterm_timeout='2', sigkill_timeout='2')
    stop_later = launch.actions.TimerAction(
        period=1.0, actions=[launch.actions.Shutdown(reason='operator stop')])

    code, _ = _run([_long_running('fake_nav2'), gateway, stop_later])
    assert code == 0


# ---- bringup の配線 ---------------------------------------------------------


def _calls(tree: ast.AST, func_name: str) -> list[ast.Call]:
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, 'id', getattr(node.func, 'attr', None)) == func_name]


def _keyword(call: ast.Call, name: str):
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _bringup_tree() -> ast.AST:
    return ast.parse((BRINGUP / 'launch' / 'bringup_launch.py').read_text('utf-8'))


def test_gateway_node_is_guarded():
    """launch を立てずに、配線だけ静的に確かめる（CI は whill_bringup を建てない）。"""
    gateways = [call for call in _calls(_bringup_tree(), 'Node')
                if isinstance(_keyword(call, 'package'), ast.Constant)
                and _keyword(call, 'package').value == 'whill_gateway']
    assert len(gateways) == 1
    on_exit = _keyword(gateways[0], 'on_exit')
    assert isinstance(on_exit, ast.Name) and on_exit.id == 'on_gateway_exit'


def test_bag_play_is_not_guarded():
    """再生が終わっても gateway は残して「再生終了」を画面に出す（ADR-0004）。

    bag play に付けると、再生が終わった瞬間にスタックごと消える。
    """
    plays = [call for call in _calls(_bringup_tree(), 'ExecuteProcess')
             if 'bag' in ast.unparse(call)]
    assert plays, 'bag play の ExecuteProcess が見つからない'
    for call in plays:
        assert _keyword(call, 'on_exit') is None
