# gateway 経由のパラメータ変更ログ。MCAP に載せて後から追跡できるようにする。
std_msgs/Header header
string node
string name
string old_value                  # 型が混在するので文字列表現で残す
string new_value
string safety_class
string source                     # "slider" | "preset:<name>" | "cli"
bool accepted
string reject_reason              # accepted=false のときだけ埋まる
