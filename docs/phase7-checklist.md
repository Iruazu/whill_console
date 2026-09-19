# Phase 7 点検票（実機に触る日）

**当日はこの文書だけを見る。** なぜその順かは `docs/phase7-plan.md`。ここは手順と判断だけ。

- 段は上から順に。**「進んでよい条件」を満たさなければ次に進まない。**
- 数字はその場で表に書き込み、あとで `docs/measurements/` に貼る
- 迷ったら止める。止めて記録するほうが、進めて原因を失うより安い

共通の前置き（各段の前に 1 回）:

```bash
cd ~/whill_platform && source scripts/env.sh
export WHILL_GATEWAY_TOKEN=$(cat ~/.config/whill/gateway-token)
ros2 daemon stop      # 前の設定の daemon が残っていると CLI が嘘をつく（K2）
```

---

## 段 0 — 電源とつながり

消える実機検証待ち: 1, 2, 10, 12, 13

### 事前条件

- [ ] **車輪が浮いている**（ジャッキアップ済み、またはスタンド上）
- [ ] 周囲に人がいない
- [ ] LiDAR・IMU・シリアルが挿さっている（`ls -l /dev/ttyUSB*`）

### 打つもの

```bash
whill run --robot cr2-01 --mode real --gateway        # 別ターミナル。閉じない
whill doctor --robot cr2-01 --mode real
whill measure telemetry --seconds 60 --mode real      # 出力をそのまま貼る
```

### 見るもの

- 起動ログに `wss://0.0.0.0:8765 で待ち受け中`
- 上部帯が「Nav2 動作中」（`起動中` が 20 秒を超えたら `応答なし` になる）
- tf パネルに「無い」「止まっている」が出ていないこと

### 記録

| 項目 | 値 |
|---|---|
| `whill doctor` の結果（欠けたトピック） | |
| バッテリー（%） | |
| 左右モータ電流（A、停止時） | |
| IMU 温度（degC） | |
| 点群の点数 / スキャンレート | |
| `whill measure telemetry` が名指しした食い違い | |

### 進んでよい条件

- [ ] `whill doctor --mode real` が全件 OK
- [ ] `whill measure telemetry` の「来ていない」「値が無い」が空

### 中止条件

- トピックが揃わない → **`cr2-base.yaml` の宣言を直してから**やり直す（推測で進めない）

---

## 段 1 — 止まることの確認（**車輪を浮かせたまま**）

消える実機検証待ち: 7, 8

### 事前条件

- [ ] **車輪が浮いている**（この段は実際に車輪が回る）
- [ ] 手の届くところに物理の電源スイッチ

### 打つもの

```bash
whill measure stop --repeats 5          # E-STOP とハートビート断、各 5 回
```

そのあと手で:

```bash
whill manual --vx 0.1 --seconds 3       # 動かす
# 画面の E-STOP を押す → 解除する → **勝手に走り出さないこと**を見る
```

最後に Wi-Fi を物理的に切る（機内モード等）→ 止まることを見る。

### 記録

| 項目 | 中央値 | 最大 | ゼロにならなかった回数 |
|---|---|---|---|
| E-STOP → 指令ゼロ | | | |
| ハートビート断 → 指令ゼロ | | | |

| 項目 | 値 |
|---|---|
| E-STOP 解除後、自律走行が再開したか（**再開してはいけない**） | |
| Wi-Fi 断で止まるまで（目視、秒） | |
| 指令ゼロのあと車輪が止まるまで（目視、惰性） | |

mock の基準線: E-STOP 中央 30 ms / ハートビート断 430 ms
（`docs/measurements/2026-09-19-stop-time-mock.md`）。**実機はこれより伸びる。**

### 進んでよい条件

- [ ] `whill measure stop` の「ゼロにならなかった回数」が **両方 0**
- [ ] E-STOP 解除後に自律走行が再開しない
- [ ] Wi-Fi を切っても止まる

### 中止条件

- **1 つでも満たさなければ、この日はここで終わり。** 原因を `docs/open-questions.md` に書く。
  「もう一度だけ」をやらない

---

## 段 2 — 接地して手動操作

消える実機検証待ち: 4

### 事前条件

- [ ] 段 1 をすべて満たした
- [ ] 人が横につく。最初は 0.1 m/s
- [ ] 前方 5 m に人・物が無い

### 打つもの

```bash
whill manual --vx 0.1 --seconds 3
whill latency --repeats 20              # 画面 → Nav2 の往復（Wi-Fi 越し）
```

### 記録

| 項目 | 値 |
|---|---|
| 往復遅延 中央値 / 最大（ms） | |
| `manual_heartbeat_timeout` 0.5 s で誤って止まったか | |
| `manual_zero_hold` 2.0 s と twist_mux 0.5 s の関係で問題が出たか | |

### 進んでよい条件

- [ ] 手動で前進・停止ができる
- [ ] 通常操作で誤ってハートビート断にならない（なるなら**値を変える前に記録**）

---

## 段 3 — 自律走行（屋内の短い区間）

消える実機検証待ち: 5, 6, 9, 18

### 事前条件

- [ ] 段 2 を満たした
- [ ] 地図がその場所のもの（`whill robots` で個体の maps を確認）
- [ ] E-STOP をすぐ押せる位置に人がいる

### 打つもの

```bash
whill tap --seconds 20 --stream tf --stream status -v      # 走行中に別ターミナルで
# 画面の配車パネルから短い区間を投入
whill latency --repeats 20                                  # 走行中のスライダー反映
```

### 記録

| 項目 | 値 |
|---|---|
| 配車の結果（SUCCEEDED / ABORTED） | |
| 走行中に tf パネルが warn / crit を出したか（どの辺、何秒） | |
| `map → odom` の更新間隔（実測、tap の tf 行） | |
| スライダー反映の遅延 中央値 / 最大（ms、予算 200） | |
| `locked_while_moving` が走行中に拒否したか | |
| 仮想障害物を置いたときの迂回（した / しない） | |
| sim で詰めた値との差（19） | |

### 進んでよい条件

- [ ] 配車が SUCCEEDED
- [ ] tf パネルが crit を出さない
- [ ] スライダー反映が 200 ms 以内

### 中止条件

- tf が crit（`map → odom` が止まる）→ **走行を止める。閾値をその場で緩めない**

---

## 段 4 — 屋外（キャンパス）

消える実機検証待ち: 11, 15, 16, 17, 20, 21, 22

### 事前条件

- [ ] 段 3 を満たした
- [ ] iPhone のインターネット共有に PC と iPad をつないだ（`docs/runbook.md` の iPad の節）
- [ ] 通信量を見る用意（カメラは 6 Hz で 10 分約 80 MB）

### 打つもの

```bash
whill run --robot cr2-01 --mode real --gateway --camera
# iPad で https://<PC の IP>:8765/ を開く（ops レイアウト）
whill tap --seconds 60 --stream telemetry -v > /tmp/outdoor-telemetry.txt
```

### 記録

| 項目 | 値 |
|---|---|
| `yaw_rate_vs_ndt` の健全時の分布（最大、deg/s） | |
| localization が外れたときの値（外れたら） | |
| iPad Safari / Chrome で開けたか、`.local` 名で開けたか | |
| 屋外での画面の見やすさ（直射日光、手袋） | |
| D435 の 1 枚の大きさ、実測レート、帯域 | |
| `rgb_camera.exposure` が実機に存在するか（`ros2 param list /camera/camera`） | |
| 通信量（10 分あたり MB） | |

### 進んでよい条件

- [ ] 屋外で ops レイアウトが操作できる
- [ ] localization の閾値を見直す材料が取れた（見直しは**記録のあと**）

---

## 段 5 — 常駐化

消える実機検証待ち: 3, 14

### 打つもの

```bash
sudo cp services/whill_stackd/whill-stackd.service /etc/systemd/system/
sudo mkdir -p /etc/whill && sudo nano /etc/whill/stackd.env    # WHILL_GATEWAY_TOKEN と TLS のパス
sudo systemctl daemon-reload && sudo systemctl enable --now whill-stackd
systemctl status whill-stackd
```

再起動して、他PC のブラウザから起動・停止できることを見る。

### 記録

| 項目 | 値 |
|---|---|
| `systemctl stop whill-stackd` の所要時間（秒） | |
| 起動中の実機PC の CPU 使用率（gateway プロセス、%） | |
| costmap の実配信レート（`whill tap` の costmap 行） | |
| tablet の描画の重さ（俯瞰図の追従が遅れるか） | |

### 進んでよい条件

- [ ] 再起動後に stackd が自動で上がる
- [ ] 他PC から起動・停止できる
- [ ] `systemctl stop` が SIGKILL まで上がらない（#65）

---

## 終わったら

- [ ] 記録した数字を `docs/measurements/2026-xx-xx-*.md` に貼る
- [ ] `docs/open-questions.md` の B 節から、消えた項目を消す（**数字か判断を書いてから消す**）
- [ ] 閾値を変えたなら、変えた理由と元の値を残す
- [ ] 残った項目と、新しく見つかったことを issue にする
