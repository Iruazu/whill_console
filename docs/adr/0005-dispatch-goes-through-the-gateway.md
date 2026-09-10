# ADR-0005: 配車は gateway を通す。手動操作は二重化しない

- 状態: 採択
- 日付: 2026-09-10
- Phase: 5

## 背景

既存スタックの配車 UI（`~/whill_lab0_ros2/src/whill_dispatch`）は、境界が
きれいに切れている。ノードは 4 つのインタフェースしか外に出していない:

```
Web -> ROS  /dispatch/submit     (String)  JSON {"waypoint"|"point","type"}
Web -> ROS  /dispatch/teleop     (String)  JSON {"active"} | {"vx","wz"}
Web -> ROS  /dispatch/cancel     (Trigger)
ROS -> Web  /dispatch/state      (String, 5 Hz)
ROS -> Web  /dispatch/waypoints  (String, 1 Hz)
```

問題は経路のほうで、**ブラウザが rosbridge に直結している**
（`whill_dispatch/web/vendor/roslib.min.js`、`dispatch_launch.py` が
9090 番で rosbridge を立てる）。設計原則 1 に反する。

## 決定

### 1. gateway が `/dispatch/*` の内側に立つ

`whill_dispatch` の**ノードは編集しない**（`CLAUDE.md`: 既存スタックは参照と
include の対象）。gateway が境界の内側で購読・publish し、Web には
`dispatch_state` / `dispatch_waypoints` / `dispatch_submit` / `dispatch_cancel`
として見せる。

`dispatch_launch.py` は **include しない。** あれは rosbridge (9090) と静的 UI の
http.server (8000) も一緒に立てる composition で、include すると ROS への口が
2 つ増える。`whill_bringup` は `dispatch_node` だけを起動する。

### 2. 手動操作（`/dispatch/teleop`）は移植しない

gateway には既に `manual_vel` + ハートビート（500 ms 断で速度ゼロ）がある。
どちらも最終的に `/cmd_vel_teleop`（twist_mux の teleop スロット、優先度 50）へ
書く。**両方を生かすと、同じスロットに 2 経路から書き込むことになる。**

そうなると「いま車体が止まっているのは、どちらのデッドマンが効いているのか」が
分からない。安全側の仕掛けは、効いているかどうかを一目で言えなければ意味が無い
（設計原則 4）。gateway 側に一本化する。

`/dispatch/state` の `teleop_active` も Web へ渡さない。使えない操作の状態を
出しても混乱するだけ。

### 3. `pose` と `battery` も渡さない

どちらも gateway が別の口で既に配っている（`pose` ストリーム、#39 の
`telemetry`）。同じ数字を 2 経路で配ると、食い違ったときにどちらが正しいか
分からない。**1 つの数字には 1 つの出どころ。**

### 4. `aligned` と `fitness` は渡す

これは「配車してよい状態か」を判断する材料で、**行き先ボタンと同じ場所に
出ているべきもの**（既存 UI も submit の隣に出していた）。別のパネルに置くと、
見ないまま押すことになる。#41 の drivers パネルで重複させないこと。

### 5. state と waypoints は 1 つのストリームにする

`dispatch_waypoints` は `dispatch_state` の従属（`stream_of()`）。独立させると
「一覧は来るのに状態が来ない」構成を作れてしまい、行き先は選べるのに進捗が
永久に止まった配車パネルができる。costmap の全量と部分更新と同じ話（ADR-0002）。

## 帰結

**得たもの**

- ブラウザが開く WebSocket から rosbridge が消えた。Playwright で機械的に
  検査している（`ws://…:9090` に繋いだら失敗する）
- 既存ノードを 1 行も触っていないので、既存スタック単体の運用は今まで通り
- 不正な submit に理由が返る。既存ノードは warn ログに書いて落とすだけで、
  UI からは「押したのに何も起きない」に見えていた

**払ったもの**

- **ブラウザからの手動操作の経路が 1 つ減った。** 既存 UI の「スタックから
  脱出させる」teleop は、本リポの手動操作に置き換わる。移行のときに操作方法が
  変わることを周知すること
- gateway が JSON-in-String をパースする層を持つことになった。既存ノードが
  カスタムメッセージを持たない（ADR-0012 choice A）ぶんの付け替え

## mock の配車地点

実機の地点（`docs/maps/campus/waypoints.yaml`）はキャンパスの map 座標にあり、
mock の廊下地図（22 m × 7 m）の外を指す。そのまま使うと**全部 ABORTED になり、
配線が壊れているのか地点が地図の外なのか区別が付かない。**

`whill_bringup/config/mock_waypoints.yaml` に廊下の中の 3 点を置いた。
寸法を変えるときは `scripts/make_mock_map.py` と一対で見直すこと。

## 分かったこと

`whill_dispatch` は **preempt しない。** 走行中に別の行き先を投入すると FIFO の
後ろに並ぶ（`queue_len` が増える）。画面の「走行中」は前の job のものなので、
押した直後に車体が別方向へ進んでいくように見える。UI は待ち数を出しているが、
**「いま押した行き先へ向かっている」とは限らない**ことは覚えておくこと。
