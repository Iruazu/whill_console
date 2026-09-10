# whill_platform 要件

出典: `whill_platform 実装計画書`（2026-09-10）。本書はそれを実装可能な粒度に落とし、
Phase 0 で確定した事実を反映したもの。計画書と食い違う箇所は本書が正で、理由を明記する。

## 1. 目的

rvize / gazebo に代わる WHILL CR 専用の Web コンソールを作り、sim・実機・log 再生を
同一画面で扱い、実機PC に触らずに他PC・tablet から開発・運用できるようにする。

対象車両は WHILL CR ×3（同型、当面 1 台ずつ）。

## 2. 設計原則

違反する提案は理由を述べて却下する。

1. **ROS は実機PC内に閉じる。** 外部との接続は `whill_gateway` の WebSocket 1 本と ssh のみ。
   多マシン DDS は構成しない。
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

### Phase 5 — drivers テレメトリと ops レイアウト

- `robots/*.yaml` の `telemetry:` 宣言（**スキーマは Phase 0 で確定済み**）
- drivers パネル: ドライバごとに概要行 + 展開詳細、縦積み。電力・温度・yaw vs ndt を含む
- ops レイアウト（tablet 幅）: 上部帯、俯瞰図（追従 ON・進行方向上）、配車、E-stop、主要テレメトリ
- 既存 Web 配車 UI の機能を ops に移植

**受け入れ**: mock が閾値超えの値を出すと該当カードが warning 色になる。768px で崩れない。

### Phase 6 — 周辺（後回し可）

camera パネル、tf パネル、`sam_infer`（uv 別プロセス、ZeroMQ）。

## 5. 作業規約

`CLAUDE.md` の「作業規約」が正。要点:

- PR は 1 フェーズ内の 1 機能単位（目安 300 行以下）
- 各 PR に 目的 / 変更点 / 検証方法 / スクリーンショット / 実機検証待ち項目
- テストなしのロジック変更はマージしない
- 設定は必ず `config/` の yaml から。ノード内へのハードコード禁止
- 分からないことは `docs/open-questions.md` に追記して止まる
