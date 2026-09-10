# runbook

資格情報は書かない。トークンやパスワードは環境変数で渡す。

## 初回セットアップ

```bash
# ツールチェーン (sudo 不要、~/.local へ入る)
curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$HOME/.local/bin" sh
# Node 22 は tarball を ~/.local/opt/node へ展開し、corepack で pnpm を有効化する
#   (apt の nodejs 12 は Vite に古すぎる)

# MCAP 再生と gateway に必要
sudo apt-get install -y ros-humble-rosbag2-storage-mcap python3-aiohttp

# python3-websockets は入れないこと。apt の 9.1 は Python 3.10 で壊れており、
# 「起動ログは正常なのに誰も繋がらない」状態になる (ADR-0003)

cd ~/whill_platform
source scripts/env.sh

# ROS
(cd ros && colcon build --symlink-install)

# CLI / stackd
(cd services && uv sync)

# Web
(cd web && pnpm install && pnpm exec playwright install chromium)
```

## 毎回

```bash
source ~/whill_platform/scripts/env.sh
```

これが `WHILL_PLATFORM_CONFIG` / `RMW_IMPLEMENTATION` / `CYCLONEDDS_URI` を設定し、
ROS → 既存スタック → 本リポの順に source する。**順序を変えないこと**
（既存リポの install に残る旧 `whill_bringup` が本リポのものを隠す）。

## gateway のトークン

gateway は **`WHILL_GATEWAY_TOKEN` が無いと起動しない**（無認証で待ち受ける
状態を作らないため）。8 文字以上。

```bash
export WHILL_GATEWAY_TOKEN=$(openssl rand -hex 16)
```

**このトークンをリポジトリに書かないこと。** `docs/` に資格情報を置かない規約。
研究室で共有するなら別の経路で渡す。

## 起動

```bash
# mock (実機なしの既定)
whill run --robot cr2-01 --mode mock

# camera も上げる (CPU を食う)
whill run --robot cr2-01 --mode mock --camera

# preset を当てる
whill run --robot cr2-01 --mode mock --preset cautious

# bag 再生 (Phase 4)
whill run --robot cr2-01 --mode replay --bag bags/2026-07-31-campus

# 起動せずコマンドだけ見る
whill run --robot cr2-01 --mode mock --dry-run
```

`services/` の外から `whill` を叩くなら `uv run --project ~/whill_platform/services whill ...`。

## 確認

```bash
# 宣言トピックが全部出ているか (Phase 0 の受け入れ判定)
whill doctor --robot cr2-01 --mode mock

# 個体一覧と TF の採寸状況
whill robots

# パラメータ
whill params list --robot cr2-01
whill params list --live
whill params show controller_server.FollowPath.min_lookahead_dist

# config/ のスキーマ検証
whill params validate

# 起動中のスタックで live パラメータが本当に即時反映されるか試す
# (試した値は元に戻す)
whill params probe
whill params probe --key controller_server.FollowPath.min_lookahead_dist

# registry から生成した Nav2 params が既存スタックと一致するか
# (Phase 1 の受け入れ条件。差分ゼロなら exit 0)
ros2 run whill_params generate_nav2_params --robot cr2-01 --check

# preset を当てたものを書き出して中身を見る
ros2 run whill_params generate_nav2_params --robot cr2-01 --preset cautious -o /tmp/nav2.yaml

# 起動せずに「出るはずのトピック」を見る
whill topics --mode mock
```

## テスト

```bash
./scripts/test.sh            # 全部
./scripts/test.sh services   # config / CLI の pytest
./scripts/test.sh ros        # registry / descriptors の pytest
./scripts/test.sh web        # vitest + Playwright スクリーンショット
```

スクリーンショットは `docs/screenshots/` に出る。UI を変えた PR には必ず添付する。
CI も同じものを撮って artifact `screenshots` に上げるので、そこから拾ってもよい。

`scripts/test.sh` は CI (`.github/workflows/ci.yml`) と同じ内容を走らせる。
ローカルで緑なのに CI で赤い、という状態を作らないため、片方に検査を足したら
もう片方にも足すこと。

CI は 3 ジョブに分かれる。壊れた場所が名前で分かるようにしてある:

| ジョブ | 内容 | ROS |
|---|---|---|
| `services` | config/ の検証、CLI のテスト、ruff | 不要 |
| `web` | 型検査、vitest、Playwright スクリーンショット | 不要 |
| `ros` | registry、ParameterDescriptor、Nav2 params 生成 | `ros:humble-ros-base` コンテナ |

`ros` ジョブには既存スタック (`whill_lab0_ros2`) が無いので、その
`nav2_params.yaml` に依存するテストは skip される。`-rs` を付けてあるので
skip の理由がログに出る（全部 skip されて緑、を見逃さないため）。
テンプレートの場所は `WHILL_NAV2_TEMPLATE` で差し替えられる。

## 落ちたとき

| 症状 | 原因と対処 |
|---|---|
| `file 'bringup_launch.py' was not found ... whill_lab0_ros2/install/whill_bringup` | source 順が逆。`scripts/env.sh` を使うこと。 |
| Nav2 が activate せず `not part of the same tree` を繰り返す | `odom -> base_link` を出す EKF が居ない。既存スタック (`whill_localization`) が source されているか確認する。 |
| `ros2 topic hz /scan` が何も出さない | `/scan` は best-effort QoS。humble の `topic hz` は自動判定しない。`ros2 topic echo --once` を使う。 |
| pytest が `No module named 'lark'` で落ちる | ROS 製 pytest プラグインの自動 load。`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` を付ける（`scripts/test.sh` は付けている）。 |
| launch が残骸プロセスを残す | `pkill -INT` は launch の子に確実に伝播しない。`pkill -9 -f whill_mock_drivers` のように子を名指しで落とす。 |
| `whill params probe` が "Node not found" と言う | registry のノード名と ROS のノード名が違う。`config/params.yaml` の `node_aliases` に実ノード名を書く（costmap は `/local_costmap/local_costmap`）。 |
| costmap を subscribe しているのに絵が固まったまま | Nav2 は全量を latched で 1 回しか出さない。`/…/costmap_updates` も受けること。ADR-0002 参照。 |
| `generate_nav2_params --check` が「N 件が反映されていない」で落ちる | registry のキー名がテンプレートの構造と合っていない。Nav2 の costmap は `local_costmap: local_costmap: ros__parameters:` と二重に入れ子になる点に注意。 |
| gateway が `WHILL_GATEWAY_TOKEN が未設定` で落ちる | 仕様どおり。無認証では起動しない。 |
| gateway は起動しているのにブラウザから繋がらない | `python3-websockets` が入っていないか確認する。入っていると壊れる（ADR-0003）。`python3-aiohttp` を使うこと。 |
| gateway が `address already in use` で落ちる | 前回のプロセスが残っている。`ss -ltnp \| grep 8765` で PID を見て落とす。 |
| `mode=real` / `mode=sim` で例外が出る | 未配線。仕様どおり（黙って起動しないより落とす）。`docs/open-questions.md` K5。 |

## bag の変換

```bash
./scripts/convert_bag_to_mcap.sh \
  ~/whill_lab0_ros2/docs/m7-bench-data/2026-07-31-live-campus/rosbag2_2026_07_31-15_14_51 \
  2026-07-31-campus
```

`bags/` は gitignore 済み。全 45 GB を変換しないこと。必要になった 1 本だけ。

## mock の地図を変えたとき

`mock_velodyne` の合成廊下と mock 用の占有格子は同じ寸法でなければならない。
片方だけ変えると「LiDAR は壁を見ているのに地図に無い」状態になる。

```bash
python3 scripts/make_mock_map.py --half-width 2.5 --length 20.0
(cd ros && colcon build --symlink-install --packages-select whill_bringup)
```
