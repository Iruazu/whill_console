# whill_platform

WHILL CR 専用の Web 開発・運用コンソール。sim・実機・log 再生を同一画面で扱い、
実機PC に触らずに他PC・tablet から開発する。

rviz / gazebo の置き換えを狙うが、**3D 表示・bag 解析・プロットは Foxglove /
Lichtblick に委譲する**。自作するのは 2D 俯瞰・パラメータ・運用・ドライバ監視だけ。

> **リポジトリ名について**: GitHub 上は `Iruazu/whill_console`。実装計画書と
> ディレクトリ・パッケージ名は `whill_platform` のままだが、`Iruazu/whill_platform`
> は別プロジェクト（Firebase 配車プラットフォーム）が先に使っていたため、
> GitHub 側だけ名前を変えた。

対象は WHILL CR ×3（同型）。既存の自律走行スタック
[`whill_lab0_ros2`](https://github.com/Iruazu/whill_lab0_ros2)（Nav2 / scan-to-map
localizer / Layer D / Web 配車 UI）は壊さず、launch から include する。

## 現在地

**Phase 0（足場）完了。** 実機は手元に無いため、すべて mock / bag 再生で検証している。

```bash
source scripts/env.sh
whill run --robot cr2-01 --mode mock   # 別ターミナルで
whill doctor --robot cr2-01 --mode mock
```

`doctor` は `cr2-base.yaml` の宣言を正として `ros2 topic list` と突き合わせる。
人が目で見る代わりに機械が判定する。

フェーズ計画は [`docs/requirements.md`](docs/requirements.md) §4。

## 構成

| ディレクトリ | 中身 | 管理 |
|---|---|---|
| `config/` | 設定の単一ソース（params / robots / presets） | git |
| `ros/` | colcon ws（msgs, params, gateway, costmap_plugins, mock_drivers, bringup） | colcon |
| `services/` | `whill` CLI と `whill_stackd` | uv |
| `web/` | React + TypeScript + Vite | pnpm |
| `sim/` | Gazebo world、障害物シナリオ | git |
| `bags/` | 再生用 MCAP（中身は gitignore） | — |
| `tests/` | pytest（services / ros） | — |
| `docs/` | 要件・ADR・runbook・未解決事項 | git |

Web 側のテスト（vitest / Playwright）は `web/tests/` にある。

## 設定の優先度

```
config/params.yaml  <  config/robots/cr2-0N.yaml  <  config/presets/*.yaml  <  スライダー
```

ノード内に設定をハードコードしない。新しいパラメータは `ParameterDescriptor` 付きで
宣言し、`config/params.yaml` に同時登録する。理由は
[ADR-0001](docs/adr/0001-config-single-source.md)。

## セットアップ・運用・詰まったとき

[`docs/runbook.md`](docs/runbook.md)。

## テスト

```bash
./scripts/test.sh          # services + ros + web
```

テストなしのロジック変更はマージしない。UI 変更は `docs/screenshots/` の
Playwright スクリーンショットを PR に添付する。

## 分からないこと

推測で埋めない。[`docs/open-questions.md`](docs/open-questions.md) に追記して止まる。

## ライセンス

BSD-3-Clause
