# スライダー → Nav2 反映の所要時間（mock 構成）

- 日付: 2026-09-10
- 構成: mock（`whill run --robot cr2-01 --mode mock --gateway`）
- 測定機: Alienware x15 R2 / Ubuntu 22.04 / ROS 2 humble
- 接続: **localhost**（同一マシン内。Wi-Fi 越しではない）
- コマンド: `whill latency --repeats 20`

## 結果

Phase 3 の受け入れ条件は **200 ms 以内**。

| パラメータ | n | total 中央 | total 最大 | network | validate | service |
|---|---|---|---|---|---|---|
| `controller_server.FollowPath.min_lookahead_dist` | 20 | 1.0 | **12.0** | 0.3 | 0.01 | 0.7 |
| `local_costmap.inflation_layer.inflation_radius` | 20 | 1.2 | 2.7 | 0.3 | 0.01 | 0.8 |
| `global_costmap.inflation_layer.cost_scaling_factor` | 20 | 1.1 | 2.3 | 0.3 | 0.01 | 0.7 |

単位は ms。**最大 12.0 ms で予算の 6 %。**

## 内訳の意味

| 項目 | 何を測っているか |
|---|---|
| `total` | クライアントの時計で測った往復（送信 → 結果の受信） |
| `network` | `total` から gateway 内の所要時間を引いたもの |
| `validate` | registry の型・範囲・`safety_class` の検査 |
| `service` | ROS の `SetParameters`（= Nav2 の応答） |

**1 つの数字にしていない理由**: 「200 ms を超えた」だけ分かっても、
ネットワークが遅いのか gateway の検査が重いのか Nav2 が返さないのか
区別できず、どこを直せばよいか分からない。

時計合わせは要らない。`total` はクライアントの時計だけ、gateway 内の内訳は
gateway の時計（`time.monotonic()`）だけで完結しており、`network` は
同じ時計同士の差の引き算。

## 読み方の注意

**最大 12.0 ms は 1 回目の呼び出し。** ROS のサービスクライアントの discovery が
入るため。2 回目以降は 2〜3 ms に収まる。運用では最初のスライダー操作だけが
わずかに遅い。

**registry の検査は 0.01 ms** で、実質ゼロ。安全側の検査（型・範囲・
`safety_class`）を入れたことによる遅延は問題にならない。

**支配項は ROS のサービス往復（0.7〜0.8 ms）。** ノードによる差は
ほとんど無く、costmap（`/local_costmap/local_costmap`）でも
controller_server でも同程度。

## この数字を信用してよい範囲

**localhost かつ mock 構成の数字。実機の代わりにはならない。**

実機で変わる要因:

- **Wi-Fi 越しの往復**。ここでは `network` が 0.3 ms だが、実機では
  これが支配項になる可能性が高い
- **実機PC の CPU 負荷**。mock は VLP-16 の実ドライバも SLAM も動いていない。
  Nav2 + センサ + gateway が同時に動く実機では `service` が伸びうる
- costmap の更新頻度。実障害物層があると Nav2 側の処理が重くなる

実機での再測定は `docs/open-questions.md` の実機検証待ちに登録してある。

## 再現方法

```bash
source scripts/env.sh
WHILL_GATEWAY_TOKEN=$(openssl rand -hex 16) \
  whill run --robot cr2-01 --mode mock --gateway   # T1
whill latency --repeats 20                          # T2
```

予算を超えると終了コード 1 で落ちる（`--budget` で変更可）。
