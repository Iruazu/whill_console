# runbook

資格情報は書かない。トークンやパスワードは環境変数かファイルで渡す。
実機で未確認の事項は `docs/open-questions.md` の B 節にある。

## 初回セットアップ

```bash
# uv（~/.local/bin）
curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$HOME/.local/bin" sh

# Node 22 と pnpm（apt の nodejs 12 は Vite に古すぎる）
mkdir -p ~/.local/opt ~/.local/bin
[ -d ~/.local/opt/node ] || {
  curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.xz | tar -xJ -C ~/.local/opt
  mv ~/.local/opt/node-v22.14.0-linux-x64 ~/.local/opt/node
}
ln -sf ../opt/node/bin/node ~/.local/bin/node
~/.local/opt/node/bin/corepack enable --install-directory ~/.local/bin

# MCAP 再生と gateway に必要。python3-websockets は入れない（ADR-0003）
sudo apt-get install -y ros-humble-rosbag2-storage-mcap python3-aiohttp

cd ~/whill_platform
source scripts/env.sh
(cd ros && colcon build --symlink-install)
(cd services && uv sync)
(cd web && pnpm install && pnpm exec playwright install chromium && pnpm build)
```

- `colcon build` が `whill_bringup` / `whill_msgs` の override を警告するのは想定どおり。
  既存スタックにも同名パッケージがあり、`env.sh` が本リポ側を後に source して優先させる
- `whill` / `whill-stackd` は `scripts/bin/` の入口（中身は `uv run`）。`env.sh` が PATH に入れる。
  `services/.venv/bin` は PATH に入れない（venv の python3 が ROS の python3 を隠す）

### gateway のトークン

gateway と stackd は `WHILL_GATEWAY_TOKEN`（8 文字以上）が無いと起動しない。
ファイルに 1 回だけ作り、毎回それを読む（毎回作ると端末に保存したトークンが使えなくなる）。

```bash
umask 077; mkdir -p ~/.config/whill
openssl rand -hex 16 > ~/.config/whill/gateway-token
```

- リポジトリに書かない。共有は別経路で
- 作り直したら各端末で入れ直す
- systemd で stackd を動かすときは同じ値を `/etc/whill/stackd.env`（600）に書く

## 起動

Claude Code とは別のターミナルで起動し、止めるときはそのターミナルで Ctrl-C。

```bash
cd ~/whill_platform
source scripts/env.sh
export WHILL_GATEWAY_TOKEN=$(cat ~/.config/whill/gateway-token)
whill run --robot cr2-01 --mode mock --gateway
```

`wss://0.0.0.0:8765 で待ち受け中`（TLS 無しなら `ws://`）が出たら `https://localhost:8765/` を開き、
トークンを入れる。上部帯が「gateway 接続」になれば成功。`whill run` を手で起動しているときの
「stackd 未接続」は正常。

```bash
whill run --robot cr2-01 --mode mock --gateway --camera            # camera も上げる（CPU を食う）
whill run --robot cr2-01 --mode mock --gateway --preset cautious   # preset を当てる
whill run --robot cr2-01 --mode replay --gateway --bag bags/2026-07-31-campus
whill run --robot cr2-01 --mode sim --gateway                      # 「sim」節を先に読む
whill run --robot cr2-01 --mode real --gateway                     # 実機未起動。docs/phase7-checklist.md 段 0 に従う
whill run --robot cr2-01 --mode mock --dry-run                     # 起動せずコマンドだけ見る
```

前のスタックが残っていると gateway が 8765 を取れず、スタックごと失敗して止まる。

## Web 画面

gateway が `web/dist/` を 8765 で配る。運用では開発サーバを起動しない。

- 他PC / tablet からは `https://<実機PC>:8765/`（TLS 未設定なら `http://`）
- 画面のコードを変えたら `(cd web && pnpm build)`。未ビルドだと `/` がビルドを案内する
- 配信元は `WHILL_WEB_ROOT` で変えられる

画面のコードを触るときは開発サーバを使う:

```bash
(cd web && pnpm dev)          # 0.0.0.0:5173。TLS 設定済みなら https
```

## 確認

```bash
whill doctor --robot cr2-01 --mode mock     # 宣言トピックが揃っているか
whill topics --mode mock                    # 出るはずのトピック（起動不要）
whill robots                                # 個体一覧と TF の採寸状況

# gateway のフレームを覗く（UI と gateway の切り分け）
whill tap --seconds 8
whill tap --seconds 5 --stream tf --stream diagnostics --verbose
whill tap --host 192.168.1.20 --seconds 5

# パラメータ
whill params list --robot cr2-01
whill params list --live
whill params show controller_server.FollowPath.min_lookahead_dist
whill params validate                       # config/ のスキーマ検証
whill params probe                          # live パラメータの即時反映（試した値は戻す）
whill tap --seconds 3 --set 'controller_server.FollowPath.min_lookahead_dist=0.75' -v
whill tap --seconds 3 --apply-preset cautious -v
whill latency --repeats 20                  # スライダー → Nav2 反映（基準 200 ms）
ros2 topic echo /whill/param_changes        # 受理・拒否の記録

# Nav2 params の生成が既存スタックと一致するか（差分ゼロで exit 0）
ros2 run whill_params generate_nav2_params --robot cr2-01 --check
ros2 run whill_params generate_nav2_params --robot cr2-01 --preset cautious -o /tmp/nav2.yaml

# 手動操作・ハートビート断・E-stop
whill manual --vx 0.25 --seconds 3 --then-silent 4
whill manual --seconds 0 --estop

# 仮想障害物（map 固定、半径 0.05〜5.0 m、200 個まで、永続化しない）
ros2 topic pub --once /whill/virtual_obstacles whill_msgs/msg/VirtualObstacleArray \
  '{header: {frame_id: map}, obstacles: [{id: t1, frame_id: map, center: {x: 4.0, y: 0.0}, radius: 1.0}]}'
ros2 topic pub --once /whill/virtual_obstacles whill_msgs/msg/VirtualObstacleArray \
  '{header: {frame_id: map}, obstacles: []}'
```

## stackd（他PC から起動・停止する）

```bash
# 実機PC 側
export WHILL_GATEWAY_TOKEN=$(cat ~/.config/whill/gateway-token)
whill-stackd

# 操作側（同じトークンを export）
whill stack status
whill stack start --mode mock --follow 25
whill stack logs --limit 50 --follow 30
whill stack restart --mode mock
whill stack stop
whill stack status --url ws://192.168.1.20:8770
```

- 停止はプロセスグループごと SIGINT → SIGTERM → SIGKILL。子が全部消えるまで「停止」と返さない
- systemd ユニットは `services/whill_stackd/whill-stackd.service`。`enable` は実機復帰後

## sim（Gazebo Classic 11）

```bash
# 初回
sudo apt-get install -y ros-humble-gazebo-ros-pkgs
python3 scripts/make_mock_map.py
(cd ros && colcon build --symlink-install --packages-select whill_bringup)

whill run --robot cr2-01 --mode sim --gateway
whill doctor --robot cr2-01 --mode sim     # odom / 点群 / scan / imu / clock
```

- 廊下は mock と同寸（22 m × 7 m、障害物 1 個）。配車地点も同じ（west / center / east）
- gzclient は出さない（3D は Foxglove）
- 起動ログに `LiDAR=GPU（NVIDIA）` が出れば GPU。`WHILL_SIM_GPU=off` で CPU に切り替え

| | 実機 | mock | sim |
|---|---|---|---|
| 車体 | WHILL CR2 | 速度の積算 | 差動二輪の箱（寸法は近似） |
| LiDAR | VLP-16 | 合成の廊下 | Gazebo の光線（16 × 900） |
| `/scan` | 点群 → 地面除去 → laserscan | mock が直接出す | 点群 → laserscan（地面除去なし） |
| map → odom | scan-to-map localizer | identity | identity（odom は滑るとずれる） |
| バッテリー等 | 出る | 出る | 出ない |
| 時刻 | 実時間 | 実時間 | `/clock` |

## DDS（CycloneDDS）

`env.sh` が `config/cyclonedds-runtime.xml` を指す。既定は loopback のみ（ROS は実機PC内で閉じる）。

```bash
echo $CYCLONEDDS_URI
export WHILL_DDS_INTERFACE=<NIC 名>     # LiDAR の有線 NIC も使うとき。ip -brief link show で確認
ros2 daemon stop                        # 設定を変えたら必ず。古い daemon がトピックを隠す
```

## iPad から開く（https / wss）

iPad のブラウザは http を開けないため、研究室 CA を作って iPad に信頼させる。
PC はアクセスポイントにせず、PC と iPad を同じネットワーク（iPhone のインターネット共有など）につなぐ。

```bash
scripts/tls/make-ca.sh                         # 1 回だけ。~/.config/whill/tls/ に作る
scripts/tls/make-server-cert.sh                # IP が変わったら再発行（397 日で失効）
scripts/tls/make-server-cert.sh 192.168.1.20   # アドレスを足す
source scripts/env.sh                          # WHILL_TLS_CERT / KEY / CA が入る
```

- `~/.config/whill/tls/ca.key` を git・クラウド・共有フォルダに置かない
- 平文で動かすときは `WHILL_TLS=off source scripts/env.sh`。証明書が片方だけ・読めないときは起動しない

iPad 側（端末ごとに 1 回、この順で）:

1. PC でスタックを起動する
2. Safari で `https://<PC の IP>:8765/whill-ca.crt` を開き、プロファイルをダウンロード（Chrome では不可）
3. 設定 → 一般 → VPN とデバイス管理 → `whill_console lab CA` をインストール
4. 設定 → 一般 → 情報 → 証明書信頼設定 → `whill_console lab CA` をオン
5. `https://<PC の IP>:8765/` を開いてトークンを入れる

トークンを間違えると理由と一緒に入力画面に戻る。上部帯の「トークンを消す」は E-STOP も届かなくなるので走行中は使わない。

## 画面の見方

上部帯:

| 表示 | 意味 |
|---|---|
| Nav2 動作中（緑） | 正常 |
| Nav2 停止中（黄） | 未 activate。`ros2 service call /lifecycle_manager_navigation/manage_nodes nav2_msgs/srv/ManageLifecycleNodes "{command: 0}"` か再起動 |
| Nav2 起動中（黄） | 起動 20 秒以内。待つ |
| Nav2 応答なし（赤） | 異常。起動ログと `ros2 node list` を見る |
| Nav2 起動しない（無色） | replay では正常 |
| 遅延 | gateway との往復時間 |
| E-STOP | gateway 未接続では押せない。解除しても走行は再開しない（goal を取り消しているため、再度ゴールを与える） |

- **tf パネル**: 辺ごとの最終受信からの経過。赤は `map → odom`（自己位置）か `odom → base_link`（EKF）の停止。閾値は `config/robots/cr2-base.yaml` の `tf.dynamic`（根拠は `docs/measurements/2026-09-14-tf-intervals.md`）
- **カメラ**: パネルを開いている間だけ流れる。表示の Hz は実測。古い画像は薄くなる。
  露出・解像度・配信レート（`whill_gateway.image_publish_rate`、既定 6 Hz ≒ 1 Mbit/s）はパラメータパネルで変える
- **俯瞰図**: ドラッグで移動、ホイールでズーム、ダブルクリックで中心。costmap が 5 秒途絶えると薄くなる
- **仮想障害物**: 「仮想障害物を置く」を入れてからクリックで配置、既存の円をクリックで削除。マゼンタの点線円。個数は常時表示
- **パラメータパネル**: `live` は操作可、`restart` は再起動が要るので操作不可、`locked` は走行中は操作不可。名前にカーソルで値の由来が出る

## テスト

```bash
./scripts/test.sh            # 全部（CI と同じ）
./scripts/test.sh services
./scripts/test.sh ros
./scripts/test.sh web        # スクリーンショットは docs/screenshots/
./scripts/live-test.sh       # 実 gateway に繋ぐ live テスト（mock + replay、約 2 分）
./scripts/live-test.sh mock
```

- UI を変えた PR にはスクリーンショットを添付する
- pnpm の版は `web/package.json` の `packageManager` で固定。外すと CI とローカルがずれる
- CI の `ros` ジョブには既存スタックが無く、それに依存するテストは skip される（理由はログに出る）
- live テストは 8765 が塞がっていると何もせず終わる。失敗時のログは `/tmp/whill-live-test/`。
  `pnpm exec playwright test` 単体では live は skip される（`WHILL_LIVE=1` が要る）

## 実機で測る（Phase 7）

実機の日は `docs/phase7-checklist.md` に従う。

```bash
whill measure telemetry --seconds 60 --mode real   # 段 0: 宣言との食い違い（あれば exit 1）
whill measure stop --repeats 5                     # 段 1: 車輪を浮かせて。ゼロにならない回があれば中止
whill latency --repeats 20                         # 段 2
```

mock の基準: E-STOP 中央 30 ms、ハートビート断 430 ms（実機の値ではない）。

## GitHub の運用

- PR 本文は `.github/pull_request_template.md` から書く。該当しない項目は「なし」
- ラベルはブランチ接頭辞・変更ファイル・`Closes #N` の issue から自動で付く
- マージ済みブランチは GitHub 側で自動削除。手元は `git fetch --prune` のあと消す
- レビュー依頼は任意: `scripts/request-review.sh <PR> copilot|devin`（依頼者の利用枠を使う）

## bag と mock 地図

```bash
# bag を MCAP に変換（必要な 1 本だけ。bags/ は gitignore）
./scripts/convert_bag_to_mcap.sh \
  ~/whill_lab0_ros2/docs/m7-bench-data/2026-07-31-live-campus/rosbag2_2026_07_31-15_14_51 \
  2026-07-31-campus

# mock の地図を変えるときは合成廊下と占有格子を同寸で作り直す
python3 scripts/make_mock_map.py --half-width 2.5 --length 20.0
(cd ros && colcon build --symlink-install --packages-select whill_bringup)
```

## 落ちたとき

| 症状 | 対処 |
|---|---|
| `whill: コマンドが見つかりません` | そのターミナルで `source scripts/env.sh` |
| `bringup_launch.py was not found ... whill_lab0_ros2/install/whill_bringup` | source 順が逆。`scripts/env.sh` を使う |
| gateway が `address already in use` | 前のスタックが残っている。`ss -ltnp \| grep 8765` で PID を見て `kill -INT` |
| gateway が `WHILL_GATEWAY_TOKEN が未設定` | 仕様。トークンを export する |
| gateway は起動しているのに繋がらない | `python3-websockets` が入っていないか（ADR-0003） |
| 「gateway error: 認証に失敗した」 | トークン違い。入力画面で入れ直す |
| Nav2 が `not part of the same tree` を繰り返す | `odom -> base_link` の EKF が居ない。既存スタックが source されているか |
| `ros2 topic list` / `whill doctor` にトピックが出ない | `ros2 daemon stop` |
| `ros2 topic hz /scan` が何も出さない | best-effort QoS。`ros2 topic echo --once` を使う |
| `rmw_create_node: failed to create domain` | `WHILL_DDS_INTERFACE` が空か重複 |
| pytest が `No module named 'lark'` | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`（`scripts/test.sh` は付けている） |
| 止めたのにノードが残る | `ros2 launch` の pid に素の `kill` をしない。Ctrl-C か `kill -INT`。残骸は `pkill -9 -f whill_mock_drivers` など子を名指し |
| `whill params probe` が "Node not found" | `config/params.yaml` の `node_aliases` に実ノード名を書く |
| `generate_nav2_params --check` が「N 件が反映されていない」 | registry のキーとテンプレートの入れ子が不一致（costmap は二重） |
| costmap が来ない／最初の 1 枚で固まる | Nav2 は全量を 1 回しか出さない。gateway を再起動し、`whill tap --verbose` で `update` 行を確認（ADR-0002） |
| replay でテレメトリが届かない | costmap が大きすぎる。`costmap_max_cells` を下げる |
| `param_set` が拒否される | 走行中の `locked_while_moving`、または `live: false`（`whill params show <key>`） |
| UI と Nav2 の値が違う | `whill tap --stream params -v` で `mismatches` を見る |
| 手動操作が届かない | `ros2 topic info /cmd_vel_teleop` の Subscription が 0 なら twist_mux が居ない |
| 仮想障害物で経路が変わらない | `global_costmap.virtual_obstacles_enabled`（要再起動）と、起動ログの `whill_virtual_obstacles` |
| 仮想障害物が消えない | 空配列を publish する |
| `whill stack` が stackd に接続できない | `whill-stackd` を起動する |
| `mode=real` が `既存スタックが見つからない` / `occupancy が見つからない` | `env.sh` を使う／個体 yaml の `maps.<default>.occupancy` のパス |
| sim が `廊下の地図が無い` | `python3 scripts/make_mock_map.py` のあと `whill_bringup` を再ビルド |
| sim で `odom -> base_link が来ていない` | 起動ログの `spawn_entity` エラーを見る |
| sim の LiDAR が `CPU` | `DISPLAY` が無いか NVIDIA モジュール未ロード。`nvidia-smi` が version mismatch なら再起動 |
| sim を 2 つ起動すると片方が動かない | `GAZEBO_MASTER_URI=http://127.0.0.1:11346` などで分ける |
| tf パネルが「map → odom が止まっている」 | localizer 停止。bag の一時停止中は正常 |
| tf パネルが「… が来ていない」 | ノード未起動か宣言が古い。食い違いは既存スタックが正 |
| カメラが来ない／レートが低い | mock は `--camera`。パネルを開く。`camera.rgb_camera.color_profile` の FPS を見る |
