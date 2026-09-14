"""gateway が終わったら launch ごと**失敗として**止める（K11, #49）。

**launch に依存しない。** 渡された event と context の属性を読むだけなので、
launch を立てずに検証できる。

## なぜ要るか

gateway はブラウザから見える唯一の口（設計原則 1）。これが起動時に死ぬ
（port 衝突、`WHILL_GATEWAY_TOKEN` 未設定、registry の読み込み失敗）と、
Nav2 やドライバだけが動き続け、**「スタックは起動しているのに誰も繋がらない」**
になる。原因はログの 1 行に埋もれ、上位（stackd / UI）からは見えない。
実測で、8765 番を塞いだ状態で起動すると 40 秒経っても Nav2・モック・
dispatch_node が生き残っていた。

## `Shutdown` だけでは足りない理由（実測）

`on_exit=Shutdown()` を付けると launch は 5 秒で止まるようになったが、
**`ros2 launch` の終了コードは 0 だった。** Humble の `LaunchService.run()` は、
イベント処理中に例外が出たときしか非 0 を返さない。

終了コード 0 だと、`whill_stackd` はそれを `stopped` と表示する
（`supervisor.py` の `_wait_for_exit`）。**上位からは「誰かが止めた」に見え、
原因を隠すという K11 の問題がそのまま残る。**

そこで、終了ハンドラで例外を投げる。launch はそれを受けて全体を止め、
終了コード 1 を返し、理由をログに出す。

## 普通の停止を失敗にしない

Ctrl-C や stackd の stop でも gateway は終わる。そのときは launch が既に
停止処理に入っている（`context.is_shutdown`）ので、何もしない。
"""

from __future__ import annotations

from typing import Any


class GatewayExited(RuntimeError):
    """gateway が launch の停止より先に終わった。"""


def on_gateway_exit(event: Any, context: Any) -> None:
    """`Node(on_exit=...)` に渡すハンドラ。

    launch の停止処理中なら何もしない。そうでなければ、終了コードに
    関わらず失敗として例外を投げる — gateway は待ち受け続けるプロセスで、
    自分から正常終了する場面が無い。0 で終わっていても異常。
    """
    if getattr(context, 'is_shutdown', False):
        return None
    raise GatewayExited(describe(getattr(event, 'returncode', None)))


def describe(returncode: int | None) -> str:
    """ログと stackd に出す理由。

    **何を確かめればよいかまで書く。** 「gateway が終了した」だけだと、
    現地で次に何を見ればよいか分からない。
    """
    code = '不明' if returncode is None else str(returncode)
    return (
        f'whill_gateway が終了した（exit {code}）。gateway が居ないとブラウザから'
        f'何も見えないので、スタック全体を止める。直前の gateway のログを確認すること。'
        f'よくある原因: 8765 番が使用中（前のスタックが残っている）、'
        f'WHILL_GATEWAY_TOKEN が未設定'
    )
