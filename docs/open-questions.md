# 未解決事項 / 実機検証待ち

分からないことを推測で埋めない。ここに追記して止まる（CLAUDE.md 作業規約）。

解決したら該当行を消し、決定の理由が残る価値のあるものは `docs/adr/` に移す。

---

## A. 人が決める必要があるもの（着手をブロックする）

| # | 内容 | 状況 |
|---|---|---|
| Q2 | **cr2-02 / cr2-03 の実機はいつ来るか。** 個体 yaml は cr2-01 のコピーで、TF は全て `measured: false`、シリアルポートと LiDAR IP は仮値。 | 未定。実車到着まで cr2-01 のみで開発する。 |
| Q3 | **既存 `whill_lab0_ros2` の扱い。** 当面は launch から include する方針だが、Layer D と配車 UI をいつ `whill_platform` へ移植するか。 | 仮決め: Phase 2 は include、移植は実機復帰後。 |

## B. 実機でしか検証できないもの（実装は進める、Done にしない）

| Phase | 内容 |
|---|---|
| 0 | モックが出す値のレンジが実ドライバと合っているか（電流、温度、点群密度）。特に `ModelCr2State` の電流値はモックでは「速度に比例」の粗い近似。 |
| 0 | `mock_velodyne` の合成廊下が、実機の `/scan` と同じ QoS・レートで costmap に入るか。QoS は実機に合わせた（best-effort）が、実データでの詰まり方は未確認。 |
| 2 | 実機PC の CPU 負荷（gateway の OccupancyGrid → RLE 変換コスト）。`whill_gateway.costmap_publish_rate` の既定 2.0 Hz が妥当かはここで決まる。 |
| 2 | Wi-Fi 越しの実測遅延。`manual_heartbeat_timeout` 0.5 s が厳しすぎないか。**厳しすぎても安易に伸ばさない**（設計原則 4）。 |
| 3 | 走行中のスライダー変更が Nav2 で安全に反映されるか。`locked_while_moving` の運用確認。 |
| 3 | スライダー操作 → Nav2 反映 200 ms 以内の実測（mock では達成できても、実機の負荷下で崩れる可能性）。 |
| 4 | 実機走行中の仮想障害物による回避（幽霊障害物テスト）。 |
| 5 | 各ドライバの実テレメトリのフィールド名がモックの想定と一致するか。 |
| 5 | 温度・電力の実値レンジ。`cr2-base.yaml` の warn/crit 閾値は推定値。 |
| 5 | tablet 実機（iPad 等）での ops レイアウトの視認性。Playwright は Chromium 768px で見ているだけで、実機 WebKit と屋外の輝度は見ていない。 |
| 全体 | 3台での `ROS_DOMAIN_ID` 分離の実確認（21 / 22 / 23 を割り当て済み、未検証）。 |

## C. Phase 0 で判明した既知の問題

| # | 内容 | 対応 |
|---|---|---|
| K1 | **`whill_lab0_ros2/install` に旧 `whill_bringup` が残っている。** src からは既に消えているが install ツリーには居座っており、source 順によっては本リポの `whill_bringup` を隠す。 | `scripts/env.sh` が既存スタック → 本リポの順に source して回避済み。恒久対応は既存リポ側で `install/` を作り直すこと。 |
| K2 | **CycloneDDS の設定が `enx00e04c6808dc`（USB-Ethernet アダプタ）を指しており、未接続時に `lo` へ落ちて multicast が無効になる。** mock では動くが、gateway を他PC から繋ぐ Phase 2 で問題になる可能性がある。 | Phase 2 で `config/cyclonedds-runtime.xml` を本リポに持ち、開発時（アダプタ無し）と実機時で切り替える。 |
| K3 | **ROS を source した shell では pytest が ROS 製プラグインを自動 load して落ちる**（`launch_pytest` → `lark` 不在）。ini の `-p no:` は load 後に読まれるので効かない。 | `scripts/test.sh` と CI の `ros` ジョブが `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` を export する。直接 pytest を叩くときも同じ変数が要る。 |
| K4 | **Playwright の WebKit を入れるには `sudo` が要る**（`playwright install --with-deps`）。 | ops-tablet プロジェクトは Chromium を 768px で使う。見たいのはレイアウトでありエンジン差ではない。実機 tablet の確認は B の実機検証待ちに計上。 |
| K5 | **`mode=real` と `mode=sim` は未配線。** 呼ぶと明示的に例外で落ちる。 | 黙って何も起動しないより落ちるほうが安全（「実機モードで動いたつもり」を防ぐ）。real は実機復帰後、sim は `sim/` の world 整備後。 |

## D. 解決済み

| # | 内容 | 結論 |
|---|---|---|
| Q1 | IMU は BNO085 か RT-USB-9AXIS-00 か | **RT-USB-9AXIS-00。** 実装計画書の `bno085` は計画者の記載ミス（2026-09-10 ユーザー確認）。換装の予定は無い。宣言名を `rt_9axis`、モックを `mock_rt_9axis`、`real_package` を `rt_usb_9axisimu_driver` に修正済み。実ドライバは LifecycleNode なので `cr2-base.yaml` に `lifecycle: true` を宣言し、real モードの launch が `configure → activate` の間に約 1.5 s の待ちを入れる必要があることを明記した。 |
