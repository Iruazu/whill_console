# ADR-0004: 再生は「観測の再現」であって「再走行」ではない

- 状態: 採択
- 日付: 2026-09-10
- Phase: 4

## 背景

`mode=replay` は Phase 0 で「bag を再生する」ところまで書いたが、通しで
動かしていなかった。`cr2-base.yaml` の `modes.replay` は `include_stack: true`、
つまり **Nav2 も起動する**設定のままになっていた。

ところが代表 bag（`bags/2026-07-31-campus`）には次が入っている:

```
/tf, /tf_static, /plan, /local_costmap/costmap, /global_costmap/costmap,
/cmd_vel, /cmd_vel_nav, /cmd_vel_safety, /cmd_vel_teleop,
/odometry/filtered, /pcl_pose, /scan, /velodyne_points, /imu/data_rep145
```

**bag が出すものと Nav2 が出すものが正面衝突する。**

- `/tf` を bag と Nav2 の両方が publish する → TF ツリーが二重になる
- `/plan` も `/…/costmap` も両方から出る → 俯瞰図に描かれているのが
  「当時の Nav2 の判断」なのか「いま動いている Nav2 の判断」なのか
  区別が付かない
- `/cmd_vel` 系も同様

この状態で「7〜8 月の走行を俯瞰図に再現する」と言っても、**何を見せられて
いるのか分からない絵**にしかならない。

## 決定

**再生は観測の再現に限る。Nav2 は起動しない。**

`modes.replay` を `include_stack: false` にし、replay モードで起動するのは
次の 2 つだけにする:

1. `ros2 bag play --clock`
2. `whill_gateway`（`use_sim_time: true`）

bag が出した costmap / plan / pose / scan をそのまま gateway が配って描く。
「あの日の走行はこう見えていた」を追体験するための機能と位置づける。

静的 TF も publish しない。bag に `/tf_static` が入っているので、こちらから
出すと二重になる。

`--loop` も使わない。ループすると `/clock` が巻き戻り、costmap の `seq` 判定や
テレメトリの「古さ」判定が壊れる。もう一度見たければ起動し直す。

## 帰結

**得たもの**

- 画面に出ているものが「bag に入っていたもの」だと断言できる。
  切り分けのときにこの保証があるかどうかは大きい
- 起動するプロセスが 2 つだけなので、再生が軽い。Nav2 一式を上げると
  実機PC の CPU を無駄に食う
- bag に無いものは出ない、という素直な挙動になる

**払ったもの**

- **「保存済みの観測を入力に Nav2 を走らせ直す」ことはできない。**
  別のパラメータでどう動いたかを比べる、という使い方は別機能になる
- bag に costmap や plan が入っていない場合、俯瞰図は寂しくなる
  （センサだけの bag だと LiDAR と pose しか出ない）

## やるなら別に切ること

「観測を入力に Nav2 を走らせ直す」は**別物**で、実現するには:

- bag から Nav2 の出力（`/plan`, `/…/costmap`, `/cmd_vel*`, `/tf` の一部）を
  除いて再生する必要がある
- `/tf` は localizer が出す `map -> odom` と EKF が出す `odom -> base_link` が
  混ざっているので、どこまでを「観測」と見なすかの線引きが要る

需要が出たら別 issue に切る。いま曖昧に両対応しようとすると、
どちらの用途でも信用できない絵になる。

## 副次的に直したこと

gateway の `status` 配信タイマーを**システム時計**で回すようにした。

`use_sim_time: true` のノードでは、ROS のタイマーは `/clock` が進んだときに
しか発火しない。bag の再生が終わると `/clock` が止まり、**status も止まる**。
すると UI からは「gateway が落ちた」ように見える。

再生が終わったことは分かるべきで、画面が固まって分からなくなるのは困る。
テレメトリのレート制限は sim 時計のままでよい（bag が進まなければ新しい
データも来ないので）。
