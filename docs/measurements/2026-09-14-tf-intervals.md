# TF の更新間隔（2026-09-14、代表 bag）

#51 で、tf パネルが「止まった」と判定する閾値を決めるために測った。

## 条件

- bag: `bags/2026-07-31-campus`（235 s、実機走行、健全）
- `/tf` の各メッセージについて、辺（親 → 子）ごとに **bag の記録時刻** の差を取った
- `/tf_static` は辺ごとに 1 通ずつ

## 結果

| 辺 | 出すもの | レート | 間隔 中央 | 95 % | 99 % | 最大 |
|---|---|---|---|---|---|---|
| map → odom | scan-to-map localizer | 10 Hz | 0.102 s | 0.110 s | 0.121 s | 0.192 s |
| odom → base_link | EKF | 30 Hz | 0.033 s | — | — | 0.047 s |

map → odom の stamp は記録時刻より平均 0.044 s 遅れていた（localizer の処理時間）。

`/tf_static`: base_link → camera_link、base_link → imu_link、base_link → velodyne。

## 判断

| 辺 | warn | crit |
|---|---|---|
| map → odom | 1.0 s | 3.0 s |
| odom → base_link | 0.5 s | 2.0 s |

- warn は健全時の最大の 5〜10 倍。健全な走行では鳴らない
- crit は「一瞬の詰まりではなく止まっている」と言える長さ。Nav2 の
  `transform_tolerance` で abort するより前に画面に出したい
- 設定は `config/robots/cr2-base.yaml` の `tf.dynamic`

## 画面での確認（gateway、replay）

gateway を起動して bag を再生し、`whill tap --stream tf -v` で見た（別の
`ROS_DOMAIN_ID` とポート）。

- 再生中: 動的な辺は 2 本とも OK
- 一時停止して 4 秒後: `map->odom:crit(4.36s)`、`odom->base_link:crit(4.34s)`
- tf フレーム 1 通は約 1.1 KB（辺 5、無い 2）。1 Hz で流す

## 読み方の注意

- bag 1 本から決めた。CPU が重いとき・屋外の長距離で localizer の間隔が
  伸びるかは見ていない（`docs/open-questions.md` の B 節）
- 古さは gateway が **受け取った実時間** で測る。bag の stamp ではない
  （sim 時計ごと止まると古さが 0 のままになるため）
