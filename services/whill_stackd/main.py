"""whill_stackd の入口。

Phase 2 のスコープ。実装が入るまでは、誤って systemd に登録して
「動いているつもり」になるのを防ぐため、起動即エラーで落とす。

Phase 2 で入れるもの:
  - HTTP/WebSocket API: 個体選択 → モード選択 → 起動 / 停止 / 再起動 / ログ tail
  - `whill run` を子プロセスとして実行し、終了コードと stdout/stderr を配信
  - systemd ユニット（作成は Phase 2、enable は実機復帰後）
"""

from __future__ import annotations

import sys


def main() -> int:
    print('whill_stackd は Phase 2 で実装する。いまは `whill run` を直接使うこと。',
          file=sys.stderr)
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
