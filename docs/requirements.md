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

- `config/params.yaml` のスキーマ確定と JSON Schema 検証（**Phase 0 で先行実装済み**）
- `whill_params`: yaml → `nav2_params.yaml` を生成し、既存 `whill_lab0_ros2` の設定と差分ゼロ
- 各パラメータに `live` / `safety_class` を付与（**Phase 0 で先行実装済み**）
- `ros2 param set` 経路で Nav2 controller の数値が即時反映されることを mock 構成で確認

**受け入れ**: `generate_nav2_params --check` が既定値のみで差分ゼロ。
`whill params list --live` が即時反映可能な一覧を出す（後者は Phase 0 で動作済み）。

### Phase 2 — gateway と stackd

`whill_gateway`（rclpy, WebSocket, JSON + binary）
- 配信: costmap（RLE）、path、pose、tf tree 要約、診断、圧縮画像（レート制限）、モード状態機械
- 受信: param set/get（registry 経由で `safety_class` を検査、変更ログを `/whill/param_changes`
  に publish → MCAP 記録）、仮想障害物 CRUD、手動速度指令（ハートビート付き）、E-stop
- 認証: 固定トークン、LAN 限定バインド

`whill_stackd`（uv, systemd ユニット）
- API: 個体選択 → モード選択 → 起動 / 停止 / 再起動 / ログ tail（WebSocket）
- `whill run` を子プロセスとして実行し、終了コードと stdout/stderr を配信

**受け入れ**: 別PC のブラウザから `ws://<lab-pc>:8765` に繋ぎ、mock 構成の costmap と pose が
届く。stackd 経由で stop → start ができ、ログが流れる。ハートビート断で手動速度指令が
ゼロになることを pytest で確認。

### Phase 3 — Web dev レイアウト

パネル: 上部帯 / overview2d / params。初期値は dev = 追従 OFF・map 固定。
Canvas 描画、TypeScript、状態は zustand。

**受け入れ**: mock 構成で costmap が描画され、スライダー操作から Nav2 の `max_vel_x` が
変わるまで 200 ms 以内（gateway のタイムスタンプで計測）。Playwright スクリーンショットが
`docs/screenshots/` に自動保存される（**保存経路は Phase 0 で動作済み**）。

### Phase 4 — 仮想障害物と再生

- `whill_costmap_plugins/virtual_obstacles`: `/whill/virtual_obstacles` を costmap 層に注入
- UI: 俯瞰図クリックで配置・削除、点線円で実障害物と区別
- `--mode replay`: MCAP 再生 + `use_sim_time`、UI 上に再生位置と速度

**受け入れ**: mock 構成で仮想障害物を置くと Nav2 の経路が迂回する。
bag 再生で 7〜8 月の走行が俯瞰図に再現される。

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
