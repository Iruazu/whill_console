# 全量を毎回送る。差分にしないのは、UI と costmap の状態がずれたときに
# 復旧できなくなるより、毎回上書きするほうが安全なため（数は高々数十）。
std_msgs/Header header
VirtualObstacle[] obstacles
