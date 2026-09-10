# whill_platform — プロジェクトメモリ

全セッションに自動で読み込まれる。**最高レバレッジな文脈**なので雑多な情報を貯めないこと。
how-to は各パッケージの README、詳細は `docs/` に寄せる。

## このリポジトリは何か

rviz / gazebo に代わる **WHILL CR 専用の Web コンソール**。sim・実機・log 再生を同一画面で扱い、
実機PC に触らずに他PC・tablet から開発・運用できるようにする。

対象車両は WHILL CR ×3（同型、当面 1 台ずつ）。既存の自律走行スタック
`~/whill_lab0_ros2`（Nav2 / scan-to-map localizer / Layer D / Web 配車 UI）は**壊さない**。
本リポは launch から既存スタックを include する側であって、置き換えではない。

## 前提と制約（最初に読むこと）

- **実機は現在手元にない。** 研究室PC（Alienware x15 R2, Ubuntu 22.04, ROS 2 Humble）のみ。
  すべてのタスクを **bag 再生・モックドライバ・sim** で検証できる形に分解する。
  実機でしか検証できない項目は `docs/open-questions.md` の「実機検証待ち」に書き、**実装は進めるが Done にしない**。
- 全セッションで `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` と `CYCLONEDDS_URI` の export が必要。
  `scripts/env.sh` を source すること（既存リポの runbook 準拠）。
- 参照ツールとして Foxglove / Lichtblick を **ローカル接続のみ** で併用してよい。**クラウド保存は禁止**。

## 設計原則（違反する提案は却下する）

1. **ROS は実機PC内に閉じる。** 外部との接続は `whill_gateway` の WebSocket 1 本と ssh のみ。
   多マシン DDS は構成しない。
2. **3D 表示・bag 解析・プロットは Foxglove / Lichtblick に委譲する。**
   自作対象は 2D 俯瞰・パラメータ・運用・ドライバ監視のみ。
3. **設定の単一ソース**（左が弱く、右が強い）:
   `config/params.yaml`（3台共通） < `config/robots/cr2-0N.yaml`（個体差） < `config/presets/*.yaml` < スライダーの一時変更
4. **安全（Layer D、E-stop）は実機PC内で完結**し、通信状態に依存しない。
   手動操作はハートビート断（500 ms）で速度ゼロ。
5. **Python 環境の分離**: ROS ノードは colcon、CLI / stackd / 推論は uv。`numpy<2` を固定。
   `uv python install` は使わない（システム python3.10 を使う。ROS の rclpy と ABI を揃えるため）。
6. **自作ノードのパラメータは必ず `ParameterDescriptor`（範囲・説明）付きで宣言する。**
   gateway がこれを introspection してスライダーを自動生成するので、descriptor がないと UI に出ない。
7. **作らないもの**: 非リアルタイム高速 sim、自作 3D、Web ターミナル、他ロボット対応。

## リポジトリ名

GitHub 上は **`Iruazu/whill_console`**（private）。ディレクトリ名・パッケージ名・
実装計画書の表記は `whill_platform` のまま。`Iruazu/whill_platform` は別プロジェクト
（Firebase 配車プラットフォーム、2026-05 に作られたもの）が先に使っていたため、
GitHub 側だけ名前を変えた。両者を混同しないこと。

## リポジトリ構成

| ディレクトリ | 中身 | 管理 |
|---|---|---|
| `config/` | params.yaml / robots / presets — 設定の単一ソース | git |
| `ros/` | colcon ws（`ros/src/` 以下） | colcon |
| `services/` | whill_cli, whill_stackd | uv |
| `web/` | React + TypeScript + Vite | pnpm |
| `sim/` | Gazebo world、障害物シナリオ | git |
| `bags/` | 再生用 MCAP の置き場 | **gitignore**（README に取得手順） |
| `tests/` | pytest（ros/）, vitest + playwright（web/） | — |
| `docs/` | requirements.md, adr/, runbook.md — **資格情報を書かない** | git |

## 作業規約（絶対）

- **PR は 1 フェーズ内の 1 機能単位**（目安 300 行以下）。粒度は `whill_lab0_ros2` の #75〜#107 を踏襲。
- 各 PR に必ず: **目的 / 変更点 / 検証方法（コマンド） / スクリーンショット（UI 変更時） / 実機検証待ち項目**
- **テストなしのロジック変更はマージしない。** UI 変更は Playwright スクリーンショットを必須添付。
- **設定は必ず `config/` の yaml から。** ノード内へのハードコード禁止。
- **新規パラメータは `ParameterDescriptor` 付き**、`config/params.yaml` に同時登録。
- 設計原則 2 の範囲を超える提案（3D 自作、他ロボット、クラウド）は**理由を述べて却下する**。
- **分からないことは推測しない。** `docs/open-questions.md` に追記して止まる。
- **main へ直接 commit / push しない。** 必ず branch + PR。マージは常にユーザーが行う。
- コメントは **"なぜ"** を書く。"何をしている" だけのコメントは要らない。
- AI が書いたと一目で分かる文体を出力しない（装飾絵文字、独白、過剰な太字、追従表現）。

## フェーズ

進捗は `docs/requirements.md` の §4 が正。現在地は各 issue のマイルストーンを参照。

| Phase | 内容 | 受け入れ（実機なしで検証可能） |
|---|---|---|
| 0 | 足場・モックドライバ ✅ | `whill run --robot cr2-01 --mode mock` で Nav2 + mock 起動、宣言トピックが揃う |
| 1 | パラメータ registry ✅ | yaml 検証・Nav2 params 生成一致が pytest で通る |
| 2 | gateway と stackd ✅ | 別PC のブラウザから costmap / pose が届く。ハートビート断で速度ゼロ |
| 3 | Web dev レイアウト | スライダー → Nav2 反映が 200 ms 以内、Playwright スクショ自動保存 |
| 4 | 仮想障害物と再生 | 仮想障害物で経路が迂回、bag 再生が俯瞰図に再現 |
| 5 | drivers テレメトリと ops | 閾値超えで warning 色、768px で ops が崩れない |
| 6 | 周辺（camera / tf / sam_infer） | 後回し可 |

## 既存スタックとの関係

`~/whill_lab0_ros2` は**参照と include の対象**であって編集対象ではない。
Nav2 の設定は `whill_params` が `config/params.yaml` から生成し、既存 `nav2_params.yaml` と
**差分ゼロで一致すること**を pytest で担保する（Phase 1）。一致が崩れたらそれは本リポ側のバグ。

## Import

@docs/requirements.md
@docs/open-questions.md
