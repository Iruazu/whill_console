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

## stackd（他PC から起動・停止する）

実機PC に ssh せずにスタックを操作するための常駐サービス。

```bash
# 実機PC 側で常駐させる
export WHILL_GATEWAY_TOKEN=$(openssl rand -hex 16)
uv run --project ~/whill_platform/services whill-stackd

# 操作側（同じトークンを export しておく）
whill stack status
whill stack start --mode mock --follow 25
whill stack logs --limit 50 --follow 30
whill stack restart --mode mock
whill stack stop

# 別PC から
whill stack status --url ws://192.168.1.20:8770
```

停止はプロセスグループごと落とす（SIGINT → SIGTERM → SIGKILL）。**親が
終了しただけでは「停止した」と返さない**。`ros2 launch` の子は SIGINT を
取りこぼすことがあり、孤児が残ると次の起動と喧嘩するため。

systemd ユニットは `services/whill_stackd/whill-stackd.service`。
**`enable` は実機復帰後**（実機なしで enable すると「動いているつもり」になる）。
トークンはユニット本体ではなく `/etc/whill/stackd.env`（600）に置くこと。

## 確認

```bash
# 宣言トピックが全部出ているか (Phase 0 の受け入れ判定)
whill doctor --robot cr2-01 --mode mock

# gateway に繋いでフレームを覗く (Phase 2 の受け入れ判定)
# ブラウザを開かずに「costmap と pose が届く」ことを確かめられる。
# UI のバグと gateway のバグを切り分けるときにも使う。
whill tap --seconds 8
whill tap --seconds 5 --stream tf --stream diagnostics --verbose
whill tap --host 192.168.1.20 --seconds 5     # 別PC の gateway へ

# パラメータを WebSocket 経由で変えてみる (受理/拒否の確認)
whill tap --seconds 3 --set 'controller_server.FollowPath.min_lookahead_dist=0.75' -v
whill tap --seconds 3 --apply-preset cautious -v

# 変更ログ (受理も拒否も残る)
ros2 topic echo /whill/param_changes

# 手動操作とハートビート断の確認
# --then-silent で「指令を止めたまま接続だけ維持する」状況を作れる
whill manual --vx 0.25 --seconds 3 --then-silent 4
ros2 topic echo /cmd_vel_teleop          # 別ターミナル

# E-stop (作動すると Nav2 の goal も取り消される。解除しても自律走行は再開しない)
whill manual --seconds 0 --estop

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

# スライダー → Nav2 反映の所要時間を測る (受け入れ条件 200 ms)
# 内訳 (network / validate / service) も出るので、超えたときにどこを
# 直せばよいかが分かる
whill latency --repeats 20

# 仮想障害物を置く / 消す (WebSocket 経由。俯瞰図からの操作は Phase 4 の後続 issue)
#   action: replace / add / remove / clear
#   frame_id は map 固定、半径は 0.05〜5.0 m、個数は 200 まで
#   **永続化しない。** gateway を再起動すると消える (docs/open-questions.md Q5)

# ROS 側から直接置く場合
ros2 topic pub --once /whill/virtual_obstacles whill_msgs/msg/VirtualObstacleArray \
  '{header: {frame_id: map}, obstacles: [{id: t1, frame_id: map, center: {x: 4.0, y: 0.0}, radius: 1.0}]}'
ros2 topic pub --once /whill/virtual_obstacles whill_msgs/msg/VirtualObstacleArray \
  '{header: {frame_id: map}, obstacles: []}'    # 全消去

# registry から生成した Nav2 params が既存スタックと一致するか
# (Phase 1 の受け入れ条件。差分ゼロなら exit 0)
ros2 run whill_params generate_nav2_params --robot cr2-01 --check

# preset を当てたものを書き出して中身を見る
ros2 run whill_params generate_nav2_params --robot cr2-01 --preset cautious -o /tmp/nav2.yaml

# 起動せずに「出るはずのトピック」を見る
whill topics --mode mock
```

## Web コンソールを開く

```bash
# 実機PC 側
WHILL_GATEWAY_TOKEN=$(openssl rand -hex 16) whill run --robot cr2-01 --mode mock --gateway
(cd web && pnpm dev)          # 0.0.0.0:5173 で待ち受ける

# 他PC / tablet から
#   http://<lab-pc>:5173
```

俯瞰図の操作:

| 操作 | 効果 |
|---|---|
| ドラッグ | 平行移動（追従中に動かすと追従が切れる） |
| ホイール | ズーム |
| ダブルクリック | その点を中心に置く |
| 車体追従 | 車体を画面中央に保つ。**dev の初期値は OFF** |
| 進行方向上 | 車体の向きを上にする。**dev の初期値は map 固定** |

仮想障害物:

| 操作 | 効果 |
|---|---|
| 「仮想障害物を置く」を入れる | 配置モード。**入れないとクリックで置かれない**（地図を動かすつもりのクリックで生えるのを防ぐ） |
| 配置モード中にクリック | その位置に置く。既にある円をクリックすると消える |
| 半径 | 配置モード中のスライダー。0.05〜5.0 m |
| 全消去 | 置いてあるときだけ出る |

**点線のマゼンタの円**で描かれる。実障害物（costmap の赤）や LiDAR（橙）とは
色も線種も変えてある — 色だけだと、色覚特性や屋外の明るいタブレットで
区別が付かなくなる。

**個数は常に表示される。** 置いたまま忘れて「なぜ経路が変か」になるのを防ぐため。
gateway を再起動すると消える（永続化しない。`docs/open-questions.md` Q5）。

costmap の更新が 5 秒途絶えると薄く描かれる。「最新のように見える古い地図」を
作らないため。

上部帯:

| 表示 | 意味 |
|---|---|
| 遅延 | gateway との**往復**。`status` の時刻との差ではない（ROS とブラウザの時計は同期していないし、replay では ROS 側が実時刻ですらない） |
| stackd | 別ポート 8770。`whill run` を手で叩く運用なら「未接続」で正常 |
| E-STOP | **gateway 未接続では押せない。** 押しても届かないものを押せるように見せない |

E-stop を押すと帯が赤くなり、全クライアントの画面に反映される。
**解除には確認が入る** — 解除は「止めるのをやめる」であって「再開する」ではなく、
gateway は E-stop 時に Nav2 の goal を取り消しているので、走らせるには
改めてゴールを与える必要がある。

パラメータパネル:

| 表示 | 意味 |
|---|---|
| `live` | そのまま操作できる |
| `restart` | ノードの再起動が要る。**操作できない**（送っても gateway が拒否する） |
| `caution` | 変更が挙動に効く |
| `locked` | `locked_while_moving`。走行中は操作できない |

パラメータ名にカーソルを合わせると、値の由来（なぜその値なのか）が出る。
**変更が拒否されると理由が変更ログに残り、入力欄は実際の値に戻る。**

`registry と実ノードの値がずれている` と出たら、誰かが `ros2 param set` で
直接変えたか、生成した params が実ノードに届いていない。

初回はトークンの入力を求められる。実機PC の `WHILL_GATEWAY_TOKEN` と同じ値を
入れる。**URL には載らない**（履歴・プロキシログに残るため）。ブラウザの
localStorage に保存される。

gateway が落ちても自動で繋ぎ直す（指数バックオフ、上限 10 秒）。ただし
**認証に失敗したときは再試行しない** — トークンが違うまま叩き続けても直らず、
原因が画面から消えるだけなので。

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
| `whill tap` で costmap が 1 通も来ない | gateway が全量を取りこぼしている可能性。Nav2 は全量を latched で 1 回しか出さないので、gateway より後に Nav2 を起動し直すと届かない。gateway を再起動する。 |
| 俯瞰図が最初の 1 枚で固まる | `costmap_update` を受けていない。`whill tap --verbose` で `update` 行が出るか確認する。 |
| `param_set` が「走行中は変更できない」で拒否される | 仕様どおり。`locked_while_moving` のパラメータは走行中に変えられない。停止してから。 |
| `param_set` が「再起動が必要」で拒否される | `live: false` のパラメータ。`whill params show <key>` で確認できる。ノードを再起動すること。 |
| UI の値と実際の Nav2 の値が違う | `params` フレームの `mismatches` を見る。`whill tap --stream params -v` で件数が出る。 |
| 手動操作が車体に届かない | `ros2 topic info /cmd_vel_teleop` で Subscription count を見る。0 なら twist_mux が居ない。mock では bringup が起動する。 |
| E-stop を解除しても走り出さない | 仕様どおり。E-stop は Nav2 の goal を取り消すので、再開には改めてゴールを与えること。 |
| `whill stack` が「stackd に接続できない」と言う | stackd が起動していない。`uv run --project services whill-stackd`。 |
| stackd で止めたのにノードが残る | `ros2 node list` で確認する。残るならプロセスグループが作れていない環境。`docs/open-questions.md` に追記して止まること。 |
| ブラウザに「gateway error: 認証に失敗した」と出る | トークンが違う。localStorage の `whill.gateway.token` を消して入れ直す（devtools か、アプリのトークン入力に戻る）。 |
| 画面は出るが何も届かない | 上部帯の接続状態を見る。`disconnected` なら gateway が落ちている、`error` なら理由が出ている。 |
| 仮想障害物を置いても経路が変わらない | `global_costmap.virtual_obstacles_enabled` が true か確認する。層の追加は再起動が要る（live: false）。起動ログに `Using plugin "whill_virtual_obstacles"` が出ているかも見る。 |
| 消したのに障害物が残る | Nav2 のリカバリでは消えない設計（人が置いたものを勝手に消さない）。空配列を publish すること。 |
| replay で gateway は動いているのにテレメトリが 1 通も届かない | costmap が大きすぎてブラウザの受信上限を超えている可能性。`whill tap -v` で `1/N に間引き` が出るか見る。`costmap_max_cells` を下げる。 |
| 俯瞰図の地図が粗い | 大きい地図は間引いて送っている。倍率は俯瞰図の右上に出る。細かいところは local costmap で見る（間引かれない）。 |
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
