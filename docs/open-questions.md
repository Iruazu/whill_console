# 未解決事項 / 実機検証待ち

分からないことを推測で埋めない。ここに追記して止まる（CLAUDE.md 作業規約）。

解決したら該当行を消し、決定の理由が残る価値のあるものは `docs/adr/` に移す。

---

## A. 人が決める必要があるもの（着手をブロックする）

| # | 内容 | 状況 |
|---|---|---|
| Q2 | **cr2-02 / cr2-03 の実機はいつ来るか。** 個体 yaml は cr2-01 のコピーで、TF は全て `measured: false`、シリアルポートと LiDAR IP は仮値。 | 未定。実車到着まで cr2-01 のみで開発する。 |
| Q7 | **設計原則 1 の文言が実態と合っていない。** 「外部との接続は `whill_gateway` の WebSocket 1 本と ssh のみ」と書いてあるが、実際にはブラウザが **`whill_stackd` (8770) にもう 1 本**開いている（Phase 2 で入れたもの。起動・停止とログ tail）。stackd は ROS を喋らない（DDS も topic も通らない）ので原則の**意図**には反していないが、文言のままだと「原則違反だから却下」の判断が使えない。#42 で機械的に検査するテストを入れたときに露見した。 | 人が決める: (a) 原則を「ROS への口は gateway 1 本。運用のための stackd を例外として認める」と書き直す、(b) stackd を gateway に統合して本当に 1 本にする。**(a) が妥当に見えるが、原則の文言は提案の却下根拠なので勝手に緩めない。** |
| Q3 | **既存 `whill_lab0_ros2` の扱い。** 当面は launch から include する方針だが、Layer D と配車 UI をいつ `whill_platform` へ移植するか。 | 仮決め: Phase 2 は include、移植は実機復帰後。 |

## B. 実機でしか検証できないもの（実装は進める、Done にしない）

| Phase | 内容 |
|---|---|
| 0 | モックが出す値のレンジが実ドライバと合っているか（電流、温度、点群密度）。特に `ModelCr2State` の電流値はモックでは「速度に比例」の粗い近似。 |
| 0 | `mock_velodyne` の合成廊下が、実機の `/scan` と同じ QoS・レートで costmap に入るか。QoS は実機に合わせた（best-effort）が、実データでの詰まり方は未確認。 |
| 2 | 実機PC の CPU 負荷（gateway の OccupancyGrid → RLE 変換コスト）。`whill_gateway.costmap_publish_rate` の既定 2.0 Hz が妥当かはここで決まる。 |
| 2 | Wi-Fi 越しの実測遅延。`manual_heartbeat_timeout` 0.5 s が厳しすぎないか。**厳しすぎても安易に伸ばさない**（設計原則 4）。localhost では往復 1 ms 未満（初回のみ 42 ms）。 |
| 3 | 走行中のスライダー変更が Nav2 で安全に反映されるか。`locked_while_moving` の運用確認。 |
| 3 | **スライダー操作 → Nav2 反映 200 ms 以内の実機での再測定。** mock / localhost では最大 12.0 ms（予算の 6 %）だが、実機では Wi-Fi 越しの往復が支配項になり、CPU 負荷で ROS のサービス応答も伸びうる。計測値: `docs/measurements/2026-09-10-param-latency.md` |
| 2 | **E-stop 解除後の復帰手順。** gateway は E-stop 時に Nav2 の goal を取り消すので、解除しても自律走行は再開しない（再開には明示的な指令が要る）。実機でこの運用が妥当かは要確認。 |
| 2 | **`manual_zero_hold` 2.0 s が実機の twist_mux タイムアウト 0.5 s に対して適切か。** 短いと Nav2 の指令が一瞬通り抜ける隙ができる。 |
| 4 | 実機走行中の仮想障害物による回避（幽霊障害物テスト）。 |
| 5 | 各ドライバの実テレメトリのフィールド名がモックの想定と一致するか。 |
| 5 | **`yaw_rate_vs_ndt` の閾値 5 / 10 deg/s は bag 1 本から決めた。** 健全時の分布は路面や速度域で変わりうる（屋外の長距離走行は未確認）。実機の localization 劣化時に本当に先に動くかも未確認。根拠と測り方は ADR-0006。 |
| 5 | **`/imu/temperature` を実ドライバが出すか。** モックは出す。`cr2-base.yaml` の `publishes` に宣言したので `whill doctor` が要求する。出さないなら宣言を外すこと。 |
| 5 | 温度・電力の実値レンジ。`cr2-base.yaml` の warn/crit 閾値は推定値。 |
| 3 | **全域 costmap（440×140 セル）を描いたときの tablet での描画負荷。** ImageData を 1 枚起こして拡大する方式にしてあるが、実機の tablet での実測は未実施。 |
| 5 | **ops のボタンの大きさと配置が屋外・片手で使えるか。** 行き先ボタン 14px/20px、E-stop は上部帯の右端（768px で接続中は 2 行目に折り返す）。Chromium 768×1024 でスクロールなしに押せることは Playwright で確認済みだが、手袋・直射日光・走行中の揺れの中では見ていない。 |
| 5 | tablet 実機（iPad 等）での ops レイアウトの視認性。Playwright は Chromium 768px で見ているだけで、実機 WebKit と屋外の輝度は見ていない。 |
| 全体 | 3台での `ROS_DOMAIN_ID` 分離の実確認（21 / 22 / 23 を割り当て済み、未検証）。 |

## C. Phase 0 で判明した既知の問題

| # | 内容 | 対応 |
|---|---|---|
| K1 | **`whill_lab0_ros2/install` に旧 `whill_bringup` が残っている。** src からは既に消えているが install ツリーには居座っており、source 順によっては本リポの `whill_bringup` を隠す。 | `scripts/env.sh` が既存スタック → 本リポの順に source して回避済み。恒久対応は既存リポ側で `install/` を作り直すこと。 |
| K2 | **CycloneDDS の設定が `enx00e04c6808dc`（USB-Ethernet アダプタ）を指しており、未接続時に `lo` へ落ちて multicast が無効になる。** mock では動くが、gateway を他PC から繋ぐ Phase 2 で問題になる可能性がある。 | Phase 2 で `config/cyclonedds-runtime.xml` を本リポに持ち、開発時（アダプタ無し）と実機時で切り替える。 |
| K3 | **ROS を source した shell では pytest が ROS 製プラグインを自動 load して落ちる**（`launch_pytest` → `lark` 不在）。ini の `-p no:` は load 後に読まれるので効かない。 | `scripts/test.sh` と CI の `ros` ジョブが `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` を export する。直接 pytest を叩くときも同じ変数が要る。 |
| K4 | **Playwright の WebKit を入れるには `sudo` が要る**（`playwright install --with-deps`）。 | ops-tablet プロジェクトは Chromium を 768px で使う。見たいのはレイアウトでありエンジン差ではない。実機 tablet の確認は B の実機検証待ちに計上。 |
| K6 | **`python3-websockets`（apt の 9.1）は Python 3.10 で動かない。** `asyncio.Lock(loop=...)` が 3.10 で削除された引数を渡す。サーバは待ち受けまで成功して**接続が来た瞬間に落ちる**ので、「起動ログは正常なのに誰も繋がらない」という気づきにくい壊れ方をする。 | aiohttp を使う（ADR-0003）。`python3-websockets` は**入れないこと**。 |
| K10 | **CI とローカルで pnpm の版が違うと、ローカルで再現できない赤が出る。** CI が最新版を拾い、新しい供給網ポリシー（`ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION`）が「24 時間以内に公開された依存」を弾いた。 | `web/package.json` の `packageManager` で版を固定（corepack が読む）。**ローカルで再現できない赤は、そのうち誰も見なくなる。** なお供給網ポリシー自体は有用なので、pnpm 10 系へ上げるときに `.npmrc` で明示的に有効化することを検討する。 |
| K8 | **`SingleThreadedExecutor` を別スレッドで回すと `use_sim_time` のノード時計が進まない**（`rclpy.spin` なら進む）。gateway はこの構成なので、sim 時計に依存した処理が全部止まる。 | gateway の内部タイミング（レート制限・ハートビート監視）は**実時間の時計**で測るようにした。そもそも帯域と安全は実時間で測るべきもの。メッセージの stamp は header から取るので bag の時刻は失われない。 |
| K9 | **`rclpy` の `wait_for_service` は executor と競合して購読コールバックごと止める。** replay（Nav2 が居ない）で全ノードが未応答のとき、gateway が「起動しているのにテレメトリが 1 通も流れない」状態になった。 | 待たない。`service_is_ready()` が false なら即座に unreachable として扱う。次にクライアントが繋いだときに再試行される。 |
| K7 | **mock と実機で cmd_vel の配線が 1 段違う。** 実機は `controller_server → /cmd_vel_nav → twist_mux → /cmd_vel → velocity_smoother → /whill/controller/cmd_vel`。mock は nav2_bringup の `navigation_launch.py` をそのまま使うため velocity_smoother が先に入り、`… → velocity_smoother → /cmd_vel → twist_mux → /whill/controller/cmd_vel` になる。影響は「E-stop のゼロが velocity_smoother を通らない」こと（mock は即停止、実機は減速カーブ）。 | E-stop としては mock のほうが厳しいので上位の検証には支障がない。`mode=real` を配線する時点で実機の順序に揃える。設定は `ros/src/whill_bringup/config/twist_mux_mock.yaml` に注記済み。 |
| K12 | **gateway の配信タイマーは宣言より 1 割ほど速い。** 実測で `status` が 1.0 Hz 宣言に対し 1.14 Hz、`telemetry` が 6.0 Hz 宣言に対し 6.72 Hz。`ClockType.SYSTEM_TIME` の時計を渡した rclpy タイマーを別スレッドの `SingleThreadedExecutor` で回している構成の性質で、Phase 2 から続いている（今回の実装で持ち込んだものではない）。 | 上限レートは帯域を守るためのもので、1 割の超過で困る場面が無いため放置する。実機PC の CPU 負荷を測る段階（B 節）で問題になったら、タイマーではなく `RateLimiter` 方式（テレメトリの間引きと同じ）に寄せること。 |
| K11 | **bag を再生し終えても gateway は残り、次の `whill run` が port 8765 を取れずに落ちる。** gateway が死んでも launch 全体は生き続けるので、「スタックは動いているのにブラウザから何も繋がらない」状態になっていた。実測で、8765 番を塞いで起動すると 40 秒経っても Nav2・モック・dispatch_node が生き残った（`WHILL_GATEWAY_TOKEN` 未設定でも同じ）。 | **解決（#49）。** gateway ノードの `on_exit` で、launch の停止処理中でなければ例外を投げる（`whill_bringup/gateway_guard.py`）。launch は 5 秒以内に全体を止めて**終了コード 1** を返し、stackd は `failed` と理由を出す。`on_exit=Shutdown()` だけでは終了コードが 0 になり、stackd が「停止」と表示して原因が隠れたままだった（Humble の launch はイベント処理中の例外でしか非 0 を返さない）。通常の停止（1.8 s → 1.9 s）と、再生終了後に gateway が残る挙動（ADR-0004）は変わらない。 |
| K5 | **`mode=real` と `mode=sim` は未配線。** 呼ぶと明示的に例外で落ちる。 | 黙って何も起動しないより落ちるほうが安全（「実機モードで動いたつもり」を防ぐ）。real は実機復帰後、sim は `sim/` の world 整備後。 |

## D. 解決済み

| # | 内容 | 結論 |
|---|---|---|
| Q4 | ブラウザ側のトークンの持ち方 | **localStorage + 初回入力。** URL のクエリ文字列は却下（履歴・プロキシログ・Referer に残る）。ビルド時の環境変数も却下（成果物に焼き込まれ、変えるたびに再ビルドが要る）。LAN 限定・研究室内の運用という前提での割り切りで、これ以上の防御は無い。共有 PC 向けに消す手段（`clearToken`）は用意してある。 |
| Q5 | 仮想障害物を永続化するか | **しない。** gateway を再起動すると消える。仮想障害物は「この配置だとどうなるか」を試す道具で、置きっぱなしにするものではない。永続化すると**前のセッションで置いた障害物が生きたまま実機の走行に影響する**という一番まずい形の忘れ方ができる。代わりに個数を UI に常時出して忘れられないようにする（#31）。「再起動したら消えていた」で驚くほうが、「消したつもりが残っていた」より被害が小さい。 |
| Q6 | 仮想障害物の `frame_id` | **`map` 固定。** 俯瞰図のクリックから作るので map 以外を使う場面が無い。曖昧にしておくと「どの座標系で置いたのか分からない障害物」ができる。将来 base_link 基準で置きたくなったら、そのとき変換を入れて広げる。 |
| Q8 | IMU の姿勢（yaw）を画面に出すか | **出さない。** RT-USB-9AXIS-00 は `orientation` を推定しておらず、`orientation_covariance[0] = -1`（REP-145 の「未推定」表明）で単位四元数を置くだけ。実 bag の全 23509 通で確認した。既存スタックの EKF も同じ理由で orientation を skip し、yaw は gyro の積分に一任している。#39 でこれを見ずに `__yaw_deg` を宣言してしまい、**「常に yaw 0 度」を正しい値として表示していた**（#40 で修正）。車体の向きは localizer の pose から出す。詳細は ADR-0006。 |
| Q1 | IMU は BNO085 か RT-USB-9AXIS-00 か | **RT-USB-9AXIS-00。** 実装計画書の `bno085` は計画者の記載ミス（2026-09-10 ユーザー確認）。換装の予定は無い。宣言名を `rt_9axis`、モックを `mock_rt_9axis`、`real_package` を `rt_usb_9axisimu_driver` に修正済み。実ドライバは LifecycleNode なので `cr2-base.yaml` に `lifecycle: true` を宣言し、real モードの launch が `configure → activate` の間に約 1.5 s の待ちを入れる必要があることを明記した。 |
