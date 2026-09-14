# カメラ画像の帯域（2026-09-14、mock）

#52 で、画像を WebSocket の JSON（JPEG を base64）のまま送るか、binary フレームに
変えるかを決めるために測った。

## 条件

- `whill run --robot cr2-01 --mode mock --gateway --camera`（stackd 経由）
- gateway は TLS（wss）、研究室 CA で検証して接続
- `image_publish_rate` は既定の 1.0 Hz。mock_realsense は 640×480 の JPEG（品質 70）を 6 Hz で出す
- 各 20 秒。接続直後のスナップショットは除いた
- 数字は **WebSocket のメッセージの大きさ**（圧縮前）。aiohttp は permessage-deflate を
  使うが、JPEG はほとんど縮まないので、線上の量もほぼこれに近い

## 結果

| 購読 | 帯域 |
|---|---|
| 既定のストリームだけ | 23.5 KiB/s |
| 既定 + 画像 | 39.4 KiB/s |
| **画像ぶんの増加** | **15.9 KiB/s（0.13 Mbit/s）** |

- 届いた画像: 19 枚 / 20 s（0.95 枚/s。レート制限どおり）
- 画像 1 枚の JSON: 中央 17.2 KiB、最大 17.3 KiB

## 判断

**base64 の JSON のまま送る。binary フレームにはしない。**

- 1 Hz なら 0.13 Mbit/s で、iPhone のテザリングでも問題にならない
- JSON のままなら、`whill tap` などの既存の道具でそのまま中身を見られる
  （binary にすると切り分けに専用の道具が要る — ADR-0002 と同じ理由）
- 画像は camera パネルを開いているあいだだけ購読する。見ていない端末は流さない

## 読み方の注意

- **mock の画像は色帯と文字だけの単純な絵**で、JPEG がよく縮む。実機の D435 で
  屋外を映すと、1 枚は数倍になりうる（推定。測っていない）
- 帯域が問題になったら、まず `image_publish_rate` を下げる（live パラメータ）。
  それでも足りなければ binary フレームを検討する
- 実機での再測定は `docs/open-questions.md` の B 節に計上した
