# sim/

`mode=sim`（Gazebo Classic 11）。起動と確認のしかたは `docs/runbook.md` の「sim」。

## world と車体はここに置いていない

**廊下の world と車体の SDF は、起動のたびに config から生成する**
（`ros/src/whill_bringup/whill_bringup/sim.py`）。手で書いたファイルを置かないのは:

- 廊下は **mock の地図と同じ寸法**でなければならない。寸法の正は `scripts/make_mock_map.py`。
  ずれると「LiDAR は壁を見ているのに地図には無い」になる
- センサの取り付け位置は**個体 yaml の `tf_static`** が正。SDF に数字を写すと、
  TF と光線の出どころが食い違う
- 車体の寸法とセンサの設定は `config/robots/cr2-base.yaml` の `sim`

食い違いは `tests/ros/test_sim.py` が検査する。

## 置くもの（これから）

- `worlds/` — 廊下では踏めない状況（斜面、狭隘部、キャンパスの一部）を再現する world
- `scenarios/` — 動く歩行者などのシナリオ

**非リアルタイム高速 sim は作らない**（設計原則 7）。world は実時間で回す。
