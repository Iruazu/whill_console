# ADR-0003: WebSocket は aiohttp で実装する（websockets ライブラリは使わない）

- 状態: 採択
- 日付: 2026-09-10
- Phase: 2

## 背景

設計原則 1 により、ROS への口は gateway の WebSocket 1 本に閉じる。
実装に使うライブラリを選ぶ必要があった。

前提として、gateway は **ROS ノード**なので colcon 側、つまり **システムの
python3.10 と apt で入る依存**で動かす（設計原則 5）。uv 側の仮想環境は
CLI と stackd のためのもので、rclpy を import する ROS ノードからは使わない。

## 決定

**aiohttp（apt の `python3-aiohttp` 3.8.1）を使う。**

`websockets` ライブラリは使わない。

## 理由

`python3-websockets` は Ubuntu 22.04 の apt では **9.1** しか入らず、これは
**Python 3.10 で動かない**。`websockets/legacy/protocol.py` が

```python
self._drain_lock = asyncio.Lock(loop=...)
```

としているが、`loop` 引数は Python 3.10 で削除された。結果:

- クライアント側: `TypeError: As of 3.10, the *loop* parameter was removed
  from Lock()`
- サーバ側: 待ち受けまでは成功するが、**接続が来た瞬間に落ちる**
  （生ソケットで確認: `Connection reset by peer`）

つまり「起動ログは正常に見えるのに誰も繋がらない」という、一番気づきにくい
壊れ方をする。実際に一度これで実装して踏んだ。

pip で新しい `websockets` を混ぜる案は取らなかった。ROS の python 環境に
apt 管理外のパッケージを差し込むと、他の ROS パッケージとの整合が崩れたときに
原因の切り分けが難しくなる。`--user` に入れればシステム全体の python3 に
影響する。**再現性を、実装の書きやすさより優先する。**

## 帰結

**得たもの**

- apt だけで依存が揃う。`package.xml` に `<exec_depend>python3-aiohttp</exec_depend>`
  と書けば rosdep で解決できる。CI のコンテナでも同じ手順で入る
- aiohttp は 3.10 で普通に動く。`heartbeat=20.0` で ping による切断検出、
  `compress=True` で permessage-deflate、`max_msg_size` の指定も揃っている
- Phase 6 以降で HTTP のエンドポイント（stackd の API、静的ファイル配信）が
  欲しくなったとき、同じライブラリで足せる

**払ったもの**

- aiohttp は WebSocket 専用ライブラリより重い。ただし gateway は 1 プロセスで
  常駐するだけなので、起動時間もメモリも問題にならない
- API が `websockets` と違うため、Web 側の資料をそのまま流用できない

## 実装上の分離

`GatewayServer` は aiohttp を知らない。`recv` / `send` / `close` の 3 つを
持つオブジェクトを受け取るだけで、aiohttp の `WebSocketResponse` は
`_AiohttpSocket` が包んで渡す。

この形にしてあるので:

- テストは同じ 3 メソッドを持つ偽物を渡せる。TCP を開かずに認証・
  ブロードキャスト・切断の筋を全部通せる
- ライブラリをもう一度替えることになっても、差し替えは `serve()` と
  `_AiohttpSocket` の 2 か所で済む

## 覆すべき条件

- Ubuntu 24.04 以降に上げて apt の `python3-websockets` が 12 以上になり、
  かつ aiohttp を使う理由（HTTP との併用）が消えたとき
- gateway の帯域が問題になり、aiohttp のオーバーヘッドが実測で効いていると
  分かったとき。その場合も、まず ADR-0002 の costmap 転送形式を見直すほうが先
