# ADR (Architecture Decision Record)

「なぜそうしたか」を残す。コードを読めば分かることは書かない。捨てた選択肢と、
その判断を覆すべき条件を書く。

| # | 内容 | 状態 |
|---|---|---|
| [0001](0001-config-single-source.md) | 設定の単一ソースを config/ の yaml に置く | 採択 |
| [0002](0002-costmap-transport.md) | costmap の転送形式は RLE JSON で開始する | 採択（暫定） |
| [0003](0003-websocket-library.md) | WebSocket は aiohttp で実装する | 採択 |
| [0004](0004-replay-is-observation-only.md) | 再生は「観測の再現」であって「再走行」ではない | 採択 |
| [0005](0005-dispatch-goes-through-the-gateway.md) | 配車は gateway を通す。手動操作は二重化しない | 採択 |
| [0006](0006-yaw-rate-not-yaw-angle.md) | localization の乖離は角度ではなく変化率で見る | 採択 |
| [0007](0007-sam-infer-is-deferred.md) | sam_infer は作らない（当面）。カメラは「見えること」に絞る | 採択 |
