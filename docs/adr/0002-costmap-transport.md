# ADR-0002: costmap の転送形式は RLE JSON で開始する

- 状態: 採択（暫定、実機の CPU 実測で見直す）
- 日付: 2026-09-10
- Phase: 0（決定）／ Phase 2（実装）

## 背景

Web コンソールの俯瞰図は `nav_msgs/OccupancyGrid` を描く。local costmap は
mock 構成の実測で 200 × 200 セル（解像度 0.05 m = 10 × 10 m）、global は
キャンパス全域でさらに大きい。これを WebSocket 1 本で他PC・tablet へ流す。

選択肢は 3 つあった: 生の OccupancyGrid を間引く / PNG に符号化 / RLE JSON。

## 決定

**RLE JSON で開始する。** 負荷が問題になったら PNG に切り替える。

`[値, 連続数, 値, 連続数, ...]` の配列で送る。OccupancyGrid の値域は
-1（未知）と 0..100 で、連続する同値が多いので RLE がよく効く。

デコーダは `web/src/lib/rle.ts`、エンコーダは Phase 2 で `whill_gateway` に置く。
**片方だけ変えないこと。**

## 帰結

**得たもの**

- 実装が最も単純で、Phase 2 を costmap 以外（param set、E-stop、ハートビート）に
  集中させられる。
- 中身が JSON なので、繋がらないときにブラウザの devtools で直接読める。
  binary だと切り分けに専用ツールが要る。
- 圧縮率が悪化したらそれ自体が「costmap に細かいノイズが乗っている」という
  信号になる。PNG だと同じ異常が見えにくい。

**払ったもの**

- 最悪ケース（市松模様のようなノイズだらけの costmap）では生データより大きくなる。
  実機の障害物層がどれだけノイジーかは実機検証待ち。
- JSON のパースコストがブラウザ側にかかる。tablet の非力な端末で 5 Hz を
  出せるかは未検証。

## Phase 1 で判明した前提（gateway の実装に直結する）

Nav2 の `Costmap2DPublisher` は **`/…/costmap` に全量を publish し続けない**。
初回（および格子サイズ・原点が変わったとき）だけ全量を latched で出し、
以後の変化は `/…/costmap_updates`（`map_msgs/OccupancyGridUpdate`、矩形の部分更新）
に流す。`publish_frequency: 2.0` は「全量を 2 Hz で出す」という意味ではない。

実測（mock 構成、静止状態、2026-09-10）:

| topic | 3 秒間の受信数 |
|---|---|
| `/local_costmap/costmap` | 1（latched の 1 通のみ） |
| `/local_costmap/costmap_updates` | 10 |

つまり **`costmap` だけを subscribe した gateway は、最初の 1 枚を出したあと
永久に固まった地図を配信する。** Phase 2 では次の両方を受けること:

1. `/…/costmap` — 全量。接続直後の初期表示と、格子が張り替わったときの再同期
2. `/…/costmap_updates` — 部分更新。`x`, `y`, `width`, `height` の矩形を
   保持中の格子に貼り込む

Web 側の `CostmapFrame` は全量前提の型なので、Phase 2 で「全量」と「部分更新」の
2 種類のフレームを持つ形に広げる。RLE 化は部分更新にもそのまま効く
（むしろ全量より圧縮が効く）ので、この決定自体は変わらない。

この挙動は `inflation_radius` を live で変えたときに実証された。全量トピックだけを
見ていると「set は成功するのに costmap が変わらない」と誤読する（実際に誤読した）。
`costmap_updates` で見れば `0.6 → 1.5` でコスト >0 のセルが 13508 → 27920 に増える。

## 実測した圧縮率（Phase 2、mock 構成、2026-09-10）

| 対象 | 格子 | RLE 後の要素数 / セル数 |
|---|---|---|
| local costmap | 200×200 (40000 セル) | **0.0451**（約 22 倍に圧縮） |
| global costmap | 440×140 (61600 セル) | **0.0393**（約 25 倍に圧縮） |

mock の合成廊下は実障害物より単純なので、実機ではこれより悪くなる。
`ratio` はフレームに載せてあるので、運用中に監視して 1.0 に近づいたら
PNG への切り替えを検討する。

## 切り替えの判断基準

次のどれかが起きたら PNG に移す（Phase 2 で実測する）:

- gateway の変換処理が実機PC の 1 コアを常時 50 % 以上使う
- Wi-Fi 越しで 2 Hz の配信が維持できない
- tablet で俯瞰図の描画が体感で引っかかる

デコーダの差し替えだけで済むよう、`Overview2D` は `CostmapFrame` 型にしか
依存させない。転送形式の詳細は `rle.ts` に閉じている。
