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

## 切り替えの判断基準

次のどれかが起きたら PNG に移す（Phase 2 で実測する）:

- gateway の変換処理が実機PC の 1 コアを常時 50 % 以上使う
- Wi-Fi 越しで 2 Hz の配信が維持できない
- tablet で俯瞰図の描画が体感で引っかかる

デコーダの差し替えだけで済むよう、`Overview2D` は `CostmapFrame` 型にしか
依存させない。転送形式の詳細は `rle.ts` に閉じている。
