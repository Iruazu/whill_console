# CycloneDDS の設定を本リポに持つ（2026-09-19、K2）

`scripts/env.sh` が既存リポ（`~/whill_lab0_ros2/configs/cyclonedds-runtime.xml`）の
設定にフォールバックしていた。持ってくる前に、**設定によって実際に差が出るのか**を測った。

## 測った 4 つ

| 名前 | 中身 |
|---|---|
| 既存 `runtime.xml` | lo + `enx00e04c6808dc`（**ドック交換で古くなった名前**）、`AllowMulticast=spdp`、`DontRoute=true` |
| 既存 `runtime-min.xml` | lo + `enx00e04c680ec9`（2026-07-31 の新しい名前）。上の 2 つの上書きを外したもの |
| 本リポ案 | lo + `${WHILL_DDS_INTERFACE:-whill-no-nic}`（既定は lo だけ） |
| 設定なし | `CYCLONEDDS_URI` を外す（Cyclone 既定 = Wi-Fi も含む全 NIC） |

この PC に USB-Ethernet は挿さっていないので、上 3 つは実質「lo だけ」になる。

## 結果: **この PC では差が無い**

| 測定 | 既存 runtime | 既存 min | 本リポ案 | 設定なし |
|---|---|---|---|---|
| discovery（publisher → 最初の 1 通、15 回） | 中央 46 ms / 最大 50 ms / 失敗 0 | 47 / 50 / 0 | 44 / 50 / 0 | 44 / 50 / 0 |
| 大きなメッセージ（460 KB の点群を 10 Hz、best-effort） | 10.1 Hz | 10.1 Hz | 10.1 Hz | 10.1 Hz |
| mock スタックが `whill doctor` を通るまで（3 回） | 1.70 / 1.69 / 1.70 s | — | 1.68 / 1.69 / 1.68 s | — |
| 起動後の `whill doctor`（5 回） | 5/5 | — | 5/5 | 5/5 |

既存リポが field で踏んだ不調（Wi-Fi / テザリングの NIC 併存で `/velodyne_points` が
3.3 Hz に低下）は、**この PC の単体構成では再現しない**。再現するのは実機側の条件
（外部 AP、実 LiDAR、複数 NIC）で、手元では確かめられない。

## 途中で踏んだ落とし穴（測定が嘘をついた）

最初の測定では「設定なし」だけが `whill doctor` に通らず 3/3 失敗した。原因は
**ROS 2 の daemon を設定間で使い回していた**こと。daemon はドメインごとに常駐し、
先に別の設定で起動したものが残っていると、`ros2 topic list` や `whill doctor` が
「トピックが見えない」と嘘をつく。

ドメインを分け、測定のたびに `ros2 daemon stop` を入れたら 4 構成とも同じになった。

**設定を変えたら `ros2 daemon stop`。** runbook に書いた。

## それでも本リポに持ってくる理由（性能ではない）

- **単一ソース。** こちらで管理していないファイルに挙動が依存していた
- **古い名前を持ち込まない。** 既存の `runtime.xml` の NIC 名は 2026-07-31 の
  ドック交換前のもの。実機で使うときに黙って無視される
- **NIC 名を焼き込まない。** `WHILL_DDS_INTERFACE` で渡す（既定は lo だけ＝設計原則 1）
- 既存リポが一度入れて外した `DontRoute=true` / `AllowMulticast` の上書きを引き継がない

## 環境変数の展開について確かめたこと

- CycloneDDS の XML は `${VAR}` と `${VAR:-既定}` を展開する
- **空に展開されると `rmw_create_node: failed to create domain` で落ちる**。
  そのため既定値は「存在しない NIC 名」にしてある（`presence_required="false"` と組で無視される）
- 同じ名前を 2 回並べても落ちる（既定値を `lo` にはできない）

## 実機検証待ち

- 実機PC での NIC 構成（LiDAR の有線 + Wi-Fi）で、lo だけに絞った状態で困らないか
- `WHILL_DDS_INTERFACE` に LiDAR の NIC を入れる運用が要るのか（ROS は実機PC内で
  閉じるので、原則どおりなら要らないはず）
