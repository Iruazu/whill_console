Phase 4 で `virtual_obstacles` layer を置く場所。

設計メモ:
- `/whill/virtual_obstacles` (whill_msgs/VirtualObstacleArray) を subscribe し、
  `updateCosts` で LETHAL_OBSTACLE を書き込む。
- 全量置換にする。差分にすると UI と costmap の状態がずれたとき復旧できない。
- 実障害物と区別できるよう、UI 側は点線円で描く（costmap 上では区別しない）。
