# whill_platform 要件

出典: `whill_platform 実装計画書`（2026-09-10）。本書はそれを実装可能な粒度に落とし、
Phase 0 で確定した事実を反映したもの。計画書と食い違う箇所は本書が正で、理由を明記する。

## 1. 目的

rvize / gazebo に代わる WHILL CR 専用の Web コンソールを作り、sim・実機・log 再生を
同一画面で扱い、実機PC に触らずに他PC・tablet から開発・運用できるようにする。

対象車両は WHILL CR ×3（同型、当面 1 台ずつ）。

## 2. 設計原則

違反する提案は理由を述べて却下する。

1. **ROS は実機PC内に閉じる。** ROS への口は `whill_gateway` の WebSocket 1 本と ssh のみ。
   多マシン DDS は構成しない。**例外は運用のための `whill_stackd` (8770) だけ**（起動・停止・
   ログ tail）。例外の条件は 3 つすべてを満たすこと: **ROS を喋らない**（DDS も topic も
   通さない）／**LAN 限定**／**gateway と同じトークンで認証する**。これ以外の口を
   増やす提案は却下する（rosbridge 9090 など）。
2. **3D 表示・bag 解析・プロットは Foxglove / Lichtblick に委譲する。**
   自作対象は 2D 俯瞰・パラメータ・運用・ドライバ監視。
3. **設定の単一ソース**: `config/params.yaml` < `config/robots/cr2-0N.yaml`
   < `config/presets/*.yaml` < スライダーの一時変更。
4. **安全（Layer D、E-stop）は実機PC内で完結**し、通信状態に依存しない。
   手動操作はハートビート断（500 ms）で速度ゼロ。
5. **Python 環境の分離**: ROS ノードは colcon、CLI / stackd / 推論は uv。`numpy<2` 固定。
   `uv python install` は使わない。
6. **自作ノードのパラメータは `ParameterDescriptor` 付きで宣言する。**
   gateway がこれを introspection してスライダーを自動生成する。
7. **作らないもの**: 非リアルタイム高速 sim、自作 3D、Web ターミナル、他ロボット対応。

## 3. 決定済みの選択（計画書 §7 の未決事項）

| 項目 | 決定 | 根拠 |
|---|---|---|
| 再生用 MCAP | **手元にある。** 既存リポ `docs/m7-bench-data/` に .db3 で計 45 GB。 | 代表 1 本（2026-07-31, 235 s, 54669 msg）を `scripts/convert_bag_to_mcap.sh` で MCAP 化し `bags/` に配置済み。全量変換はしない。 |
| Web フレームワーク | **React + Vite** | Foxglove Extension 互換を残すため。 |
| costmap 転送形式 | **RLE JSON で開始** | 負荷次第で PNG。判断材料は実機PC の CPU 実測（実機検証待ち）。ADR-0002。 |
| 認証 | **固定トークン**（`WHILL_GATEWAY_TOKEN`）+ LAN 限定バインド | これ以上の防御は無い前提で運用する。 |
| systemd 化 | **Phase 2 でユニット作成、enable は実機復帰後** | 実機なしで enable すると「動いているつもり」になる。 |
| 既存 Layer D | **Phase 2 は include、移植は実機復帰後** | 既存スタックを壊さない。 |
| Web 画面の配信 | **gateway が `pnpm build` の成果物を 8765 番で配る**（#56）。開発サーバ（Vite、5173）は画面のコードを触るときだけ | 現場で起動するものを減らす。画面と WebSocket が同じオリジン・ポート・証明書になる。WebSocket は `/` へのアップグレード要求で振り分け、CLI の接続先を変えない。 |
| 設計原則 1 と stackd | **原則を「ROS への口は gateway 1 本。運用のための stackd を例外として認める」と書き直す**（Q7、2026-09-16 ユーザ判断）。例外の条件は 3 つ（ROS を喋らない / LAN 限定 / 同じトークン） | stackd は ROS を喋らないので原則の意図には反していない。一方、文言が実態と違うままだと「原則違反だから却下」が使えなくなる。統合（stackd を gateway に入れる）は、自分を止める係が自分の中にある構造になり、停止・再起動・停止中のログが成立しない |
| sam_infer（推論） | **作らない（当面）。** 用途が未確定のため凍結し、カメラは「画像が見えること」に絞る（ADR-0007、#54） | 目的が決まらないとモデル・速さ・入力・安全区分のどれも決められない。とくに Nav2 に効かせるなら「後回し可の周辺機能」ではなくなる |
| 屋外の接続 | **PC をアクセスポイントにしない。iPhone のインターネット共有に PC と iPad をつなぐ**。https / wss は研究室 CA（#55） | PC のインターネット（Claude Code・GitHub）を止めない。iPad は http を https に上げるので TLS が要る。2026-09-14 に iPad の Safari で確認。 |

## 4. フェーズ計画

各フェーズは実機なしで検証できる受け入れ条件を持つ。実機依存は `docs/open-questions.md` へ。

### Phase 0 — 足場 ✅ 完了（2026-09-10）

- リポジトリ、ディレクトリ、`CLAUDE.md`、uv / pnpm / colcon の初期化
- `whill_mock_drivers`: 4 ドライバのモックが `cr2-base.yaml` の宣言どおりに publish する
- `bags/` に代表 MCAP を 1 本配置
- Playwright のスクリーンショット自動取得

**受け入れ**: `whill run --robot cr2-01 --mode mock` で Nav2 + モックが起動し、
`whill doctor` が宣言トピック 6 件すべての publish を確認する。→ **達成**

Phase 0 で追加した判定手段: `whill doctor` は `ros2 topic list` を人が目で見る代わりに、
`cr2-base.yaml` の宣言を正として機械的に突き合わせる。

### Phase 1 — パラメータ registry

- `config/params.yaml` のスキーマ確定と JSON Schema 検証（**Phase 0 で先行実装済み**、
  **CI 化まで完了**）
- `whill_params`: yaml → `nav2_params.yaml` を生成し、既存 `whill_lab0_ros2` の設定と差分ゼロ（**完了**）
- 各パラメータに `live` / `safety_class` を付与（**Phase 0 で先行実装済み**）
- `ros2 param set` 経路で Nav2 controller の数値が即時反映されることを mock 構成で確認（**完了**）

**受け入れ**: `generate_nav2_params --check` が既定値のみで差分ゼロ。
`whill params list --live` が即時反映可能な一覧を出す（後者は Phase 0 で動作済み）。

`whill params probe` を追加した。起動中のスタックに対して live パラメータを
実際に `set` → `get` → 復元し、`live: true` が実態と合っているかを機械判定する。
実測（2026-09-10, mock 構成）で **21 件すべて即時反映**を確認済み。

Phase 1 で判明したこと: Nav2 の costmap は名前空間とノード名が同じため
`local_costmap: local_costmap: ros__parameters:` と**二重に入れ子**になる。
一段しか辿らない実装は costmap のキーを黙って書き飛ばし、値比較だけの
`--check` は「差分なし」と嘘をつく。`--check` は**反映できなかったキーがあれば
失敗する**ようにしてある。

### Phase 2 — gateway と stackd ✅ 完了（2026-09-10）

`whill_gateway`（rclpy, WebSocket, JSON + binary）
- 配信: costmap（RLE。**全量 `/…/costmap` と部分更新 `/…/costmap_updates` の両方**を
  受けること。全量は初回と格子張り替え時しか来ない — ADR-0002 参照）、path、pose、
  tf tree 要約、診断、圧縮画像（レート制限）、モード状態機械
- 受信: param set/get（registry 経由で `safety_class` を検査、変更ログを `/whill/param_changes`
  に publish → MCAP 記録。**宛先ノード名は `registry.ros_node()` を通すこと** —
  costmap は yaml のキーと ROS のノード名が違う）、仮想障害物 CRUD、
  手動速度指令（ハートビート付き）、E-stop
- 認証: 固定トークン、LAN 限定バインド。**トークン未設定では起動しない**
  （無認証で待ち受ける状態を作らない）
- 実装は aiohttp。`websockets` ライブラリは Ubuntu 22.04 の apt 版（9.1）が
  Python 3.10 で壊れているため使わない（ADR-0003）

`whill_stackd`（uv, systemd ユニット）
- API: 個体選択 → モード選択 → 起動 / 停止 / 再起動 / ログ tail（WebSocket）
- `whill run` を子プロセスとして実行し、終了コードと stdout/stderr を配信

**受け入れ**: 別PC のブラウザから `ws://<lab-pc>:8765` に繋ぎ、mock 構成の costmap と pose が
届く。stackd 経由で stop → start ができ、ログが流れる。ハートビート断で手動速度指令が
ゼロになることを pytest で確認。→ **達成**

Phase 2 で分かったこと:

- Nav2 は costmap の全量を publish し続けない。gateway は全量を保持し、
  接続時と購読変更時に配る必要がある（ADR-0002）
- `websockets` ライブラリは apt 版（9.1）が Python 3.10 で壊れている。
  aiohttp を使う（ADR-0003）
- **mock に twist_mux が無く、車体がそもそも動いていなかった。** Nav2 が出す
  `/cmd_vel` を誰も消費しておらず、goal は accept されるので気づきにくかった
- 停止は親の終了だけで判断しない。プロセスグループが空になるまで段階を上げる
- **ROS 2 の daemon は設定を跨いで嘘をつく。** ドメインごとに常駐するので、
  `CYCLONEDDS_URI` を変えても古い daemon が残り、`ros2 topic list` や
  `whill doctor` が「見えない」と言う。設定を比べる測定は daemon を止めてから
  （これで一度、存在しない不具合を 3 回再現したと思い込んだ）
- **「#13 以降で埋める」と書いた固定値が 4 フェーズ残った**（#67）。上部帯の
  Nav2 状態は常に inactive で、パラメータの「走行中は触らせない」表示も
  一度も働いていなかった。**固定値は、それを見るテストを書かない限り気づけない。**
  値を配るところまで作ったら、配った値が変わることを 1 つはテストで押さえる
- Nav2 が active かどうかと「いま車体が動いているか」は別。後者は `/cmd_vel`
  から判定して status に載せる（手動操作でも動くため）

### Phase 3 — Web dev レイアウト ✅ 完了（2026-09-10）

パネル: 上部帯 / overview2d / params。初期値は dev = 追従 OFF・map 固定。
Canvas 描画、TypeScript、状態は zustand。

Phase 3 で分かったこと:

- **遅延は往復で測る。** `status` の `stamp` との差では測れない — ROS の時刻と
  ブラウザの時計は同期しておらず、replay では ROS 側が実時刻ですらない
- 座標変換は 1 か所に閉じる。散らすと「path だけ 1 セルずれる」という
  原因を追いにくいバグになる
- **拒否されたとき、入力欄を実際の値に戻す。** 値が変わらないので素朴に
  実装すると拒否された値が残り、「効いたように見えて効いていない」表示になる

**受け入れ**: mock 構成で costmap が描画され、スライダー操作から Nav2 の値が
変わるまで 200 ms 以内（gateway のタイムスタンプで計測）。Playwright スクリーンショットが
`docs/screenshots/` に自動保存される。→ **達成**

実測（mock / localhost、2026-09-10）は中央値 1.0〜1.2 ms、最大 12.0 ms で予算の 6 %。
内訳は network 0.3 / validate 0.01 / service 0.7 ms。
詳細と読み方の注意は `docs/measurements/2026-09-10-param-latency.md`。
**実機では Wi-Fi 越しの往復が支配項になるので、この数字は実機の代わりにならない。**

### Phase 4 — 仮想障害物と再生 ✅ 完了（2026-09-10）

- `whill_costmap_plugins/virtual_obstacles`: `/whill/virtual_obstacles` を costmap 層に注入
- UI: 俯瞰図クリックで配置・削除、点線円で実障害物と区別
- `--mode replay`: MCAP 再生 + `use_sim_time`、UI 上に再生位置と速度

**受け入れ**: mock 構成で仮想障害物を置くと Nav2 の経路が迂回する。
bag 再生で 7〜8 月の走行が俯瞰図に再現される。→ **達成**

Phase 4 で分かったこと:

- **再生は「観測の再現」であって「再走行」ではない。** bag が出す `/tf` `/plan`
  `/…/costmap` `/cmd_vel*` と Nav2 が出すものが正面衝突するので、replay では
  Nav2 を起動しない（ADR-0004）
- 「gateway は生きているのにテレメトリが 1 通も流れない」が **3 つの別原因**で
  起きた: `wait_for_service` が executor と競合（K9）／別スレッドの
  `SingleThreadedExecutor` で sim 時計が進まない（K8）／全域 costmap
  6640×6295 = 41.8M セルが WebSocket の上限を超える（ADR-0002 の追記、間引きで対処）
- 間引きはブロックの**最大値**を取る。平均だと細い壁が消え、「障害物が無い」
  ように見える
- 再生位置は**止まっていることが分かる形**で出す。止まっている絵が
  「再生が終わった」のか「その時刻に車体が止まっていた」のか区別できないと、
  bag を見る意味が薄れる。「一時停止」と「再生終了」も分けて出す
- 再生速度は**観測値**（`/clock` の進み ÷ 実時間）。指令値を出すと、実機PC が
  重くて遅れている状況を見逃す。止まっているあいだは速度を出さない
  （「停止中 1.0x」は矛盾している）
- **シークは作らない。**「まだ作っていない」ではなく「作らないと決めた」
  ものとして拒否する（ADR-0004）

### Phase 5 — drivers テレメトリと ops レイアウト ✅ 完了（2026-09-13）

- `robots/*.yaml` の `telemetry:` 宣言（**スキーマは Phase 0 で確定済み**、
  gateway が読んで配るところまで完了）
- drivers パネル: ドライバごとに概要行 + 展開詳細、縦積み。電力・温度・yaw vs ndt を含む
- ops レイアウト（tablet 幅）: 上部帯、俯瞰図（追従 ON・進行方向上）、配車、E-stop、主要テレメトリ
- 既存 Web 配車 UI の機能を ops に移植（**gateway 経由。rosbridge は使わない** — ADR-0005）

**受け入れ**: mock が閾値超えの値を出すと該当カードが warning 色になる。768px で崩れない。→ **達成**

Phase 5 で分かったこと（随時追記）:

- **telemetry 宣言は Phase 0 から入っていたが誰も読んでいなかった。** 宣言だけ
  あって配線が無い状態は、スキーマ検証が通るぶん気づきにくい
- `__rate` は**実測**を返す。宣言値を返す実装は「宣言 10 Hz なのに実際は 4 Hz」を
  見つけるという目的を反転させる。途絶えたら `unknown` ではなく 0 Hz（一番
  気づきたい故障が一番目立たない色になるため）
- **既存 `whill_dispatch` はノードを触らずに使える。** 境界が `/dispatch/*` の
  4 つに切れている。移すべきは経路のほうで、ブラウザ → rosbridge 直結を
  gateway 経由に置き換える（ADR-0005）
- **手動操作は二重化しない。** `/dispatch/teleop` と gateway の `manual_vel` は
  同じ twist_mux スロットに書く。両方生かすと「どちらのデッドマンが効いて
  いるのか」が分からなくなる
- `whill_dispatch` は **preempt しない。** 走行中の投入は FIFO の後ろに並ぶので、
  画面の「走行中」が今押した行き先とは限らない
- **`widget: bar` は目盛りが引けるものだけ棒にする。** 宣言に最大値が無い
  （warn / crit しか持たない）ので、`%` 以外は数字で出す。目盛りの無い棒は
  「半分くらい」という嘘の印象を与える
- **level を色だけで伝えない。** 屋外のタブレットでは輝度と角度で色が当てに
  ならず、色覚の差もある。文字（OK / 注意 / 異常 / 古）を必ず添える
- 畳んだカードでも **warn / crit / stale の項目は全部出す。** 隠れていると
  カードを開く理由に気づけない
- **RT-USB-9AXIS-00 は姿勢（orientation）を推定していない。** `covariance[0] = -1`
  で「未推定」を表明しており、四元数は単位のまま。見ずに `__yaw_deg` を宣言すると
  「常に yaw 0 度」を正しい値として表示することになる（#39 で実際にそうなった）
- **localization の乖離は角度ではなく変化率で見る。** 角度どうしだと基準の推定が
  要るうえ、健全な bag で 28 % の標本が warn 以上になる。変化率なら健全時
  最大 3.06 deg/s / TF 凍結時 15 deg/s 前後で綺麗に分かれる（ADR-0006）
- **閾値は実測から決める。** 「なぜ 5 と 10 か」を数字で言えない閾値は、
  誤検知が出たときに直しようがない
- **レイアウトは明示的に切り替え、初回だけ画面幅で決める。** 幅だけで自動に
  するとデスクトップで ops を確認できず、見ている最中に画面を回すと入れ替わる。
  選択は localStorage に残す（リロードで dev に戻ると屋外で全スライダーが出る）
- **ops の「主要テレメトリ」は `cr2-base.yaml` の `ops: true` が決める。**
  運用中に見るのは「目的地まで保つか（battery）」「LiDAR が生きているか
  （scan_rate — 落ちると Nav2 が止まる）」「自分の位置を分かっているか
  （yaw_rate_vs_ndt）」の 3 つ。電流・温度は切り分けの数字なので dev で見る
- **進行方向上で costmap だけ逆に回っていた（Phase 3 から）。** `worldToCanvas` の
  y 反転で回転の向きが入れ替わるのに、costmap の描画だけ `rotate(-rotation)` に
  していた。map 固定では同じ絵になるので dev では気づけず、ops で進行方向上を
  既定にしたことで露見した。Phase 3 のテストは「絵が変わる」ことしか見て
  いなかった。セル中心の写像が `worldToCanvas` と一致することを 7 方向で固定した

### Phase 6 — 周辺（後回し可）

camera パネル、tf パネル。**`sam_infer` は作らない**（ADR-0007。用途が決まるまで凍結）。

**受け入れ**: camera パネルで画像がドライバのレート（mock 6 Hz）で見え、露出・解像度を
パラメータから変えられる。tf パネルが止まった辺と来ていない辺を出す。→ **達成**

Phase 6 で分かったこと（随時追記）:

- **モックのパラメータ名は実ドライバに合わせる**（#53）。独自の名前（`width` /
  `height`）のままだと、params.yaml に実機の名前を書いた瞬間、mock では
  「知らないパラメータ」になり、実機なしで一度も動かないスライダーができる。
  ノード名（`/camera/camera`）も揃える
- 実ドライバのパラメータには**出どころが 2 つある**。launch で宣言されるもの
  （`rs_launch.py` に名前がある）と、**起動時にセンサの option から生えるもの**
  （`rgb_camera.exposure`）。後者はその機体が option を持つかで決まるので、
  ソースを読んでも存在は確定できない。テストも 2 系統に分けてある
- **個体 yaml の TF が実機と 3 か所ずれていた**（tf パネルが検出）。camera_link の親が
  velodyne になっていた（実機は base_link）、IMU と LiDAR の値が noetic 時代のまま、
  誰も publish しない base_footprint を宣言していた。**既存スタックが正**なので写し直し、
  食い違いを検出するテストを入れた（`tests/services/test_tf_static_parity.py`）。
  カメラは実機で使っていないので、宣言だけが古いまま残っていた
- **効いたことが画像で分かるようにする。** 露出をモックの明るさに効かせて
  いないと、スライダーが実際に届いたかを実機なしで確かめられない
- **入力と同じレートに制限すると取りこぼす。** 6 Hz のカメラを 6 Hz に制限したら
  実測 4.3 Hz しか通らなかった（到着が周期をわずかに下回るたびに 1 枚落ちる）。
  レート制限は帯域を守るためのもので、宣言どおりに来た入力を 3 割捨てるのは
  目的から外れている。周期の 1 割の揺れを許すようにした
- **descriptor の範囲は `min + n*step` しか受け付けない。** `min: 0.1, step: 0.5` で
  既定 6.0 を置いたら gateway が起動しなくなった。範囲を足すときは既定値が
  刻みに乗るか確かめること

- **tf は親子関係だけでは止まったことが分からない。** 以前の要約は親子が変わった
  ときだけ流していたので、localizer が固まっても画面は健全なときと同じ絵だった。
  辺ごとに最後に届いた実時間を持ち、止まっていても 1 Hz で流す。閾値は
  `cr2-base.yaml` の `tf.dynamic`（代表 bag の実測から決めた）
- **静的な辺と動的な辺を分けて受ける。** `/tf_static` は止まっていて正常
- **来ていない辺を「無い」と出す。** 無いフレームは木に現れないので、黙っていると
  気づけない。これで cr2-01 の `tf_static` が bag と食い違っていることが分かった
- ops では木を出さず、止まったときだけ一行で出す。tf は既定の購読に入れた
  （パネルを開いていない端末でも止まったことが届くように）

### mode=sim（K5 の一部、2026-09-16）

Gazebo Classic 11 で `whill run --mode sim --gateway` が起動し、配車で走る。

**受け入れ**: 上部帯が「Nav2 動作中」、tf パネルに異常なし、`whill doctor --mode sim` が
5 件を確認、配車で east まで走り切る（22.4 s、3 回とも）。→ **達成**
（`docs/measurements/2026-09-16-sim-acceptance.md`）

分かったこと:

- **Humble の組み合わせは Gazebo Classic 11。** Nav2 Humble 自身の sim 例が Classic を使う。
  Ignition（Fortress）は `ros_gz` のブリッジとプラグイン名を自前で組む手数が増える
- **実機の `/scan` は LiDAR の生データではない。** 点群 → 地面除去 → `pointcloud_to_laserscan`
  （frame=base_link）で作られている。sim も点群だけを出し、同じノード・同じ設定で `/scan`
  を作る。Gazebo から LaserScan を直接出すと、傾けて付けた LiDAR が床を障害物として拾う
- **`whill run` が uv の venv を ROS に持ち込んでいた。** `#!/usr/bin/env python3` の ROS
  スクリプトが venv の python3 で動き、`spawn_entity.py` が `No module named 'lxml'` で
  落ちた。mock では該当スクリプトを使っておらず、表に出ていなかった
- **`whill doctor` が中身の無い合格を出していた。** 宣言が 0 件のモードで「0 件すべて
  publish されている」。0 件なら判定しないと言うようにした
- **ハイブリッド GPU の on-demand では、指定しないと Intel で描画する。** PRIME の
  オフロード指定を launch が付ける
- gazebo_ros の `/clock` は既定 10 Hz。use_sim_time のノードから見た時刻が 0.1 s 刻みに
  なるので 100 Hz に上げた

### Phase 7 — 実機に戻る

計画は `docs/phase7-plan.md`（2026-09-19）。要点:

- **`mode=real` は既存スタックを include する。ただし Nav2 だけは本リポが起動する。**
  既存の `nav_launch.py` は params ファイルを受け取れないので、include すると
  registry が効かず、画面のスライダーと実際の値が食い違う（設計原則 3）
- **安全から始める。** 車輪を浮かせて「止まること」（E-STOP、ハートビート断、Wi-Fi 断）を
  確認してから接地する。E-STOP が効かなければ以降を中止する
- 実機検証待ち 20 件（open-questions B 節）を、どの段で消すかまで割り当ててある
- Layer D と配車の移植（Q3）は Phase 7 ではやらない。**実機で動く配線を変えながら
  実機検証をすると、失敗の原因が切り分けられない**

## 5. 作業規約

`CLAUDE.md` の「作業規約」が正。要点:

- PR は 1 フェーズ内の 1 機能単位（目安 300 行以下）
- 各 PR に 目的 / 変更点 / 検証方法 / スクリーンショット / 実機検証待ち項目
- テストなしのロジック変更はマージしない
- 設定は必ず `config/` の yaml から。ノード内へのハードコード禁止
- 分からないことは `docs/open-questions.md` に追記して止まる
