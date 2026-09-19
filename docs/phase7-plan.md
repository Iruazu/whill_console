# Phase 7 — 実機に戻る（計画）

実車が手元に戻った日に何を、どの順でやるかを先に決めておくための文書。
**実機が無いいま書けることを全部書き、実機でしか決められないことは「決める場」だけ用意する。**

前提: Phase 0〜6 は完了。`mode=mock` / `mode=sim` / `mode=replay` は動く。
`mode=real` だけが未配線（`docs/open-questions.md` K5）。

---

## 1. この Phase の目的

| # | 目的 | 終わったと言える条件 |
|---|---|---|
| G1 | **`mode=real` が動く** | `whill run --robot cr2-01 --mode real --gateway` で実機が起動し、`whill doctor --mode real` が宣言トピックを全部確認する |
| G2 | **画面から実車を安全に止められる** | E-STOP を押してから車輪が止まるまでを実測し、ハートビート断でも止まることを確認する |
| G3 | **実機検証待ちの 23 件を消す** | `docs/open-questions.md` の B 節が空になる（各項目に実測値か判断が入る） |
| G4 | **常駐化** | systemd で stackd が上がり、再起動後も他PC から起動・停止できる |

G2 は G1 より先に済ませる（下の順序を参照）。

---

## 2. 実機が来る前にできること（いま）

- [ ] **`mode=real` の launch を書く**（下の §3）。実機なしでも「何を include するか」は
      既存スタックを読めば決まる。起動できないので `--dry-run` 相当の静的テストまで
- [ ] **cold boot は何もしなくてよいことを確認する。** WHILL CR2 は電源投入後
      `SetPower` を送るまでデータを出さないが、**既存ドライバに対処が入っている**
      （`third_party/ros2_whill/whill_driver/src/whill_node.cpp` の `Initialize()` で
      `SetPowerOn()` ×2 → `SendSetJoystickCommandWithLocal()` → `StartSendingData`。
      経緯は既存リポ `docs/ja/session-2026-05-06.md`）。**CLI に手順を足さない。**
      `cr2-base.yaml` の `cold_boot_sequence` は「ドライバが何をするか」の記録として残す。
      実機では「電源投入 → `whill run` だけで `/whill/states/model_cr2` が出る」ことを確認する
- [ ] 実機検証待ちのうち **測り方（スクリプト）だけ先に書ける**もの（§5 の「準備」列）

## 3. `mode=real` の配線（G1）

**既存スタックを include する。ただし Nav2 だけは本リポが起動する**（理由は下）。
既存リポは編集しない（CLAUDE.md: 参照と include の対象）。

```
whill_bringup/bringup_launch.py (mode=real)
├── whill_safety/m6r_bringup_launch.py   … センサ + 実ドライバ + EKF + scan-to-map localizer
│                                           + failsafe_node + twist_mux（safety 100 / teleop 50 / nav 10）
├── whill_perception  patchworkpp_node   … 地面除去（/velodyne_points → /velodyne_points_no_ground）
├── pointcloud_to_laserscan              … 既存の設定ファイルをそのまま使う（sim と同じ）
├── nav2_bringup/navigation_launch.py    … **本リポが生成した params** で起動（mock / sim と同じ）
├── nav2_map_server                      … 個体 yaml の maps.<default>.occupancy
├── whill_dispatch/dispatch_node         … 本リポが直接起動（rosbridge と http.server は使わない。ADR-0005）
└── whill_gateway                        … 本リポ
```

**`whill_navigation/nav_launch.py` は include しない。** あれは Nav2 一式を
あちらの `nav2_params.yaml` で起動するもので、**params ファイルを受け取る引数が無い**
（引数は `site` / `map_variant` / `speed` だけ。確認済み）。include すると本リポの
registry が効かず、画面のスライダーが指す値と実際の値が食い違う（設計原則 3 違反）。

代わりに、あの launch が組んでいる鎖のうち**本リポに無いもの（patchwork++）だけを借り**、
Nav2 は mock / sim と同じ形で起動する。`generate_nav2_params --check` が
**あちらのテンプレートと差分ゼロ**を保証しているので、値が変わるわけではない。

### 決めること（実機の前に決められる）

| # | 論点 | 選択肢 | いまの見立て |
|---|---|---|---|
| D1 | **Nav2 のパラメータをどちらが出すか** | (a) 既存 `nav_launch.py` に任せる / (b) 本リポの registry から生成する | **(b)。決着済み**: `nav_launch.py` は params ファイルを受け取れない（引数は site / map_variant / speed のみ）。(a) だとスライダーが効かない。値そのものは `--check` が差分ゼロを保証している |
| D2 | **twist_mux をどちらが起動するか** | (a) 既存 `safety_launch.py`（safety 100 / teleop 50 / navigation 10） / (b) 本リポ | **(a)**。Layer D と同じ launch にいるべきで、gateway は teleop スロット（50）に書くだけ（ADR-0005 の前提と一致） |
| D3 | **Layer D と配車をいつ本リポへ移すか（Q3）** | (a) 当面 include のまま / (b) Phase 7 で移す | **(a)**。実機で動く配線を変えながら実機検証をすると、失敗の原因が切り分けられない |
| D4 | **mock と実機で違う cmd_vel の順序（K7）** | 実機は `twist_mux → velocity_smoother`、mock は逆 | 実機の順序に合わせる。mock 側を直すのは Phase 7 のあと（mock を先に変えると、いま緑のテストの意味が変わる） |

### 実機でしか決められないこと

- 実ドライバの起動順と待ち（`rt_9axis` は LifecycleNode で configure → activate に約 1.5 s、
  `cr2-base.yaml` に宣言済み）
- USB の列挙順（LiDAR の有線 NIC 名、`/dev/ttyUSB*` の symlink）

---

## 4. 実機に触る日の順序

**安全から始める。走らせるのは最後。** 各段で「失敗したら次に進まない」条件を置く。

### 段 0: 電源とつながり（車輪を浮かせる / ジャッキアップ）

1. 電源投入から `whill run` だけで `/whill/states/model_cr2` が出ること
   （cold boot はドライバ側で対処済み。手順を足さない）
2. `whill doctor --mode real` で宣言トピックが揃うこと
3. `whill tap --stream telemetry` でバッテリー・電流・温度が実値で出ること
   → **ここで `cr2-base.yaml` の warn/crit（推定値）を実測で置き換える**（B 節 5 の 2 件）

### 段 1: 止まることの確認（**車輪を浮かせたまま**）

1. 画面の E-STOP → `/cmd_vel` がゼロになるまでの時間を実測
2. ハートビート断（`whill manual --then-silent`）→ 500 ms 以内にゼロ
3. Wi-Fi を切る → 止まる（設計原則 4。通信状態に依存しない）
4. E-STOP 解除後に**勝手に走り出さない**こと（B 節の「復帰手順」）

→ ここが通らなければ以降を中止する。

### 段 2: 接地して手動操作（人が横で押さえる、低速）

1. `whill manual --vx 0.1` で前進・停止
2. `manual_zero_hold` 2.0 s と実機 twist_mux のタイムアウト 0.5 s の関係を確認（B 節）
3. 手動中に画面の遅延（往復）を実測 → `manual_heartbeat_timeout` 0.5 s の妥当性

### 段 3: 自律走行（屋内の短い区間）

1. 地図と localizer（scan-to-map）が生きていること。**tf パネルで `map → odom` が
   止まらないこと**（#51 の閾値がここで初めて実データに当たる）
2. 配車で短い区間を走る
3. 走行中のスライダー変更（`locked_while_moving` の運用確認）
4. 仮想障害物を置いて迂回すること（幽霊障害物テスト）

### 段 4: 屋外（キャンパス）

1. iPhone テザリング + iPad で ops レイアウトを実運用（#55 の未確認分もここ）
2. 屋外の直射日光での視認性、手袋での押しやすさ
3. `yaw_rate_vs_ndt` の閾値を実データで見直す（B 節）
4. カメラの帯域と露出（#53 の実機確認、D435 の `rgb_camera.exposure` の存在確認）

### 段 5: 常駐化（G4）

1. systemd で stackd を enable（`services/whill_stackd/whill-stackd.service`）
2. 再起動 → 他PC のブラウザから起動・停止できること
3. `systemctl stop` の所要時間（#65 で直した停止経路の実機確認）

---

## 5. 実機検証待ち 23 件の割り当て

`docs/open-questions.md` の B 節（2026-09-19 時点で 23 件）。**どの段で消すかを先に決める。**
当日に「これはいつやるのか」を考えないため。番号は B 節の上からの並び。

| 段 | 消える項目（B 節の番号） | 準備（実機なしで書ける） |
|---|---|---|
| 0 | 1 モックの値レンジ、2 実機 `/scan` の QoS・レート、10 テレメトリのフィールド名、12 `/imu/temperature` の有無、13 温度・電力のレンジ | `whill tap --stream telemetry` を一定時間記録し、min/max と欠損を出すスクリプト |
| 1 | 7 E-STOP 解除後の復帰、8 `manual_zero_hold` と twist_mux のタイムアウト | E-STOP からゼロまで、ハートビート断からゼロまでを測るスクリプト（mock で先に動かす） |
| 2 | 4 Wi-Fi 越しの遅延と `manual_heartbeat_timeout` | `whill latency` をそのまま使う |
| 3 | 5 走行中のスライダー、6 反映 200 ms の再測定、9 仮想障害物の回避、18 tf の閾値 | `whill latency --repeats`、tf の記録（#51 の tap 出力） |
| 4 | 11 `yaw_rate_vs_ndt` の閾値、15 ops のボタン、16 iPad Chrome / mDNS、17 D435 の帯域、20 テザリングの通信量、21 カメラのパラメータ、22 ops の視認性 | 帯域の測定スクリプト（#70 で書いたもの）、屋外の記録手順 |
| 5 | 3 実機PC の CPU 負荷と `costmap_publish_rate`、14 tablet の描画負荷 | `top` の記録手順、画面側の描画時間の測り方 |
| 別 | 19 sim の車体が近似であること（sim で詰めた値を実機で確かめ直す）、23 3 台での `ROS_DOMAIN_ID` 分離 | 19 は段 3 の結果と突き合わせる。23 は 2 台目が来てから（Q2） |

**項目が増えたらこの表も増やす。** `tests/services/test_phase7_plan.py` が件数の食い違いで落ちる。

---

## 6. リスクと、先に決めておく撤退条件

| リスク | 兆候 | どうする |
|---|---|---|
| 実ドライバのトピック名・型が宣言と違う | `whill doctor` が MISSING を出す | **宣言（`cr2-base.yaml`）を直す。** モックを実機に合わせる（#53 と同じ向き） |
| 実機の CPU で gateway が重い | costmap の配信が宣言レートに届かない、画面が飛ぶ | `costmap_publish_rate` / `costmap_max_cells` を下げる。それでも足りなければ ADR-0002 の PNG 転送を再検討 |
| localizer が屋外で外れる | tf パネルが `map → odom` の crit、`yaw_rate_vs_ndt` が warn | 走行を止める。閾値の見直しは**記録を取ってから**（その場で緩めない） |
| 実機で E-STOP が効かない | 段 1 で落ちる | **以降を中止。** 原因を `docs/open-questions.md` に書いて止まる |
| 既存スタックを壊す | 既存の launch が起動しなくなる | 本リポは include するだけで既存リポを編集しない。壊したら `git -C ~/whill_lab0_ros2 status` で確認 |

---

## 7. この計画で作る issue（実機が来る前に着手できるもの）

1. **`mode=real` の launch を書く**（上の構成、D1・D2 を反映）。実機が無いので起動はできない。
   できるのは「include の構成が宣言どおりか」の静的テストと `--dry-run` まで
2. **段 0〜2 の測定スクリプト**（テレメトリの記録、E-STOP の所要時間、ハートビート断）。
   実機の前に mock で動かしておく — 当日に道具を書かない
3. **実機に触る日の点検票**（段ごとのチェックリストを `docs/` に。当日は判断を減らす）

`mock` の cmd_vel 順序を実機に合わせる（K7）のは、**実機確認が終わってから**。
いま変えると、緑のテストの意味が変わったまま実機に行くことになる。

実機が来てから切る issue は、段ごとに 1 本（段 0〜5 で 6 本）。

---

## 8. この文書の扱い

実機が来たら、この文書を見ながら進め、**各段の結果を `docs/measurements/` に残す**。
判断が変わったらここを書き換える（計画は当たらないが、当たらなかったことが分かる形にしておく）。
