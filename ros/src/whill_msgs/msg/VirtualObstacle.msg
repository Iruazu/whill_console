# UI から置く仮想障害物。costmap プラグインが読んで層に注入する。
string id                         # UI が採番する UUID。削除はこれで指定する
string frame_id                   # 通常 "map"
geometry_msgs/Point center
float32 radius                    # m
