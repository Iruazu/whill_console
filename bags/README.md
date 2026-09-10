# bags/

再生用 MCAP の置き場。**中身は gitignore 済み**（この README だけコミットされる）。

## 取得手順

元データは既存リポ `~/whill_lab0_ros2/docs/m7-bench-data/` に rosbag2 の sqlite3
(.db3) 形式で入っている（2026-07-20 / 07-21 / 07-24 / 07-31 のキャンパス実走、計 45 GB）。

MCAP へは 1 本ずつ変換する。全量変換しないこと。

```bash
./scripts/convert_bag_to_mcap.sh \
  ~/whill_lab0_ros2/docs/m7-bench-data/2026-07-31-live-campus/rosbag2_2026_07_31-15_14_51 \
  2026-07-31-campus
```

## 代表 bag

`2026-07-31-campus` — 235 s / 54669 msg / 1.5 GiB。

replay の検証にこれを使う理由は、Phase 4 で俯瞰図に出したいトピックが一通り
揃っているため:

| トピック | 用途 |
|---|---|
| `/local_costmap/costmap`, `/global_costmap/costmap` | 俯瞰図の背景 |
| `/plan` | 経路の描画 |
| `/pcl_pose`, `/odometry/filtered` | 車体位置 |
| `/scan`, `/velodyne_points` | LiDAR の 2D 投影 |
| `/tf`, `/tf_static` | フレーム変換 |
| `/cmd_vel`, `/cmd_vel_nav`, `/cmd_vel_safety` | Layer D が介入した箇所の確認 |
| `/alignment_status` | localization の劣化（実機で再発している故障モード）の再現 |

## 再生

```bash
whill run --robot cr2-01 --mode replay --bag bags/2026-07-31-campus
```

`use_sim_time` はモード宣言 (`cr2-base.yaml` の `modes.replay`) から自動で入る。
