# mode=sim の受け入れ（2026-09-16）

K5 のうち `mode=sim` を配線したときの確認。

## 条件

- Gazebo Classic 11.10.2、gazebo_ros 3.9.0
- GPU: GeForce RTX 3080 Ti Laptop（ドライバ 595.91.07、`prime-select` は on-demand）
- LiDAR は `gpu_ray`（NVIDIA で描画。`nvidia-smi` に `gzserver` 157 MiB）
- 起動: ユーザが打つのと同じ `whill run --robot cr2-01 --mode sim --gateway`

## センサの出力（5 秒平均）

| トピック | レート | frame | 中身 |
|---|---|---|---|
| `/velodyne_points` | 10.0 Hz | velodyne | 13005 点（900 × 16 のうち届いたもの） |
| `/scan` | 10.0 Hz | base_link | 720 本（実機の bag と同じ本数・同じ frame） |
| `/whill/odom` | 20.0 Hz | odom | 宣言は 2.5 Hz。速いのは上位に害が無い |
| `/imu/data_rep145` | 99.8 Hz | imu_link | 傾けた取り付け（roll -4° / pitch -8°）なので重力が 3 軸に出る |
| `/clock` | 99.8 Hz | — | gazebo_ros の既定 10 Hz から上げた |

**`/scan` が地図と一致すること**: 原点で左 2.33 m / 右 2.34 m / 正面 9.84 m。地図の壁の
内面は ±2.35 m / 9.85 m。

## 配車（gateway 経由、`dispatch_submit` → east）

| 回 | 結果 | 所要 | 終了位置 | 障害物中心からの最小距離 |
|---|---|---|---|---|
| 1（launch 直起動） | SUCCEEDED | 22.4 s | (6.52, 0.00) | 0.80 m |
| 2（`whill run`） | SUCCEEDED | 22.4 s | (6.50, 0.00) | 0.80 m |
| 3（`whill run`） | SUCCEEDED | 22.4 s | (6.49, 0.00) | 0.80 m |

- east の目標は x=7.0。Nav2 の `xy_goal_tolerance` 0.5 m 以内で止まるので 6.5 前後で成功
- 走行中、tf パネルの異常は 0。上部帯は「Nav2 動作中」
- **地図に無い障害物（6.0, 0.8, 半径 0.3）が local costmap に載った**（中心のコスト 99、
  縁 100、廊下中央 0）。点群 → `/scan` → obstacle_layer の鎖が効いている
- `whill doctor --mode sim`: 5 件すべて OK

## 読み方の注意

- 車体は近似（差動二輪の箱）。22.4 s という数字は sim の車体での値で、実機の所要時間ではない
- 障害物は経路（y=0）から 0.8 m 離れていて、避ける動きは起きていない。**避けるかどうかは
  この測定では見ていない**（見ているのは「costmap に載るか」まで）
