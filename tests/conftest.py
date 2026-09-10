"""テスト全体の共通設定（tests/ros と tests/services の両方に効く）。

async なテスト関数を pytest-asyncio 無しで動かす。

理由: ROS を source した shell では pytest が ROS 製プラグインを自動 load して
落ちるため `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` を使っている。この状態では
pytest-asyncio も load されないので、`@pytest.mark.asyncio` が無視されて
コルーチンが await されないまま「通った」ことになる。**通っていないのに緑**が
一番危ないので、プラグインに頼らず自前で回す。

マーカーの有無に関わらず、コルーチンのテスト関数は全て拾う。マーカーを
付け忘れたテストが黙って素通りするほうが危ない。

やることは小さい: コルーチンのテスト関数を見つけたら `asyncio.run` に渡すだけ。
テストごとに新しいイベントループになるので、状態が漏れない。
"""

from __future__ import annotations

import asyncio
import inspect

import pytest


def pytest_configure(config):
    # マーカーを登録しておかないと PytestUnknownMarkWarning が出る。
    # 実際の実行は下の pytest_pyfunc_call が担う。
    config.addinivalue_line(
        'markers', 'asyncio: コルーチンのテスト。conftest が asyncio.run で回す')


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """コルーチンのテスト関数を実行する。同期のものは既定の処理に任せる。"""
    test_function = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_function):
        return None

    kwargs = {name: pyfuncitem.funcargs[name]
              for name in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(test_function(**kwargs))
    return True
