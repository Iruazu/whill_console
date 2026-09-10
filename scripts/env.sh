# whill_platform の環境設定。各ターミナルで source する。
#
#   source ~/whill_platform/scripts/env.sh
#
# 冪等。何度 source しても同じ状態になる。

# このファイル自身の場所からリポジトリ根を決める（cd してから source しても効く）
_whill_env_src="${BASH_SOURCE[0]:-$0}"
WHILL_PLATFORM_ROOT="$(cd "$(dirname "$_whill_env_src")/.." && pwd)"
export WHILL_PLATFORM_ROOT
export WHILL_PLATFORM_CONFIG="${WHILL_PLATFORM_ROOT}/config"

# 既定の FastDDS は velodyne_msgs 級の大メッセージで間欠的に詰まる。
# 既存リポで実証済みなので、ここは選択の余地なく cyclonedds に固定する。
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# CycloneDDS の設定。bag 録画時だけそのターミナル限定で差し替える運用は
# 既存リポ (configs/cyclonedds-bag-record.xml) を踏襲する。
if [ -f "${WHILL_PLATFORM_ROOT}/config/cyclonedds-runtime.xml" ]; then
  export CYCLONEDDS_URI="file://${WHILL_PLATFORM_ROOT}/config/cyclonedds-runtime.xml"
elif [ -f "${HOME}/whill_lab0_ros2/configs/cyclonedds-runtime.xml" ]; then
  # 移行期は既存リポの設定をそのまま使う。whill_platform 側に持ってくるのは
  # 実機復帰後（設定が本当に同一かを実機で確認してから）。
  export CYCLONEDDS_URI="file://${HOME}/whill_lab0_ros2/configs/cyclonedds-runtime.xml"
fi

# ~/.local/bin (uv, node, pnpm) を通す
case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) ;;
  *) export PATH="${HOME}/.local/bin:${PATH}" ;;
esac

# ROS 2 humble
if [ -f /opt/ros/humble/setup.bash ]; then
  # shellcheck disable=SC1091
  . /opt/ros/humble/setup.bash
fi

# 既存スタックを先に、本リポを後に source する。順序が逆だと
# whill_lab0_ros2/install に残っている旧 whill_bringup (M2/M3 期の成果物で
# src からは既に消えている) が本リポの whill_bringup を隠す。実際に踏んだので
# この順序は動かさないこと。
if [ -f "${HOME}/whill_lab0_ros2/install/setup.bash" ]; then
  # shellcheck disable=SC1091
  . "${HOME}/whill_lab0_ros2/install/setup.bash"
fi

# 本リポの colcon ws（同名パッケージがあるとき勝つ側）
if [ -f "${WHILL_PLATFORM_ROOT}/ros/install/setup.bash" ]; then
  # shellcheck disable=SC1091
  . "${WHILL_PLATFORM_ROOT}/ros/install/setup.bash"
fi

# 個体ごとの ROS_DOMAIN_ID。WHILL_ROBOT_ID を先に export しておくと拾う。
# 3台同時運用時の分離が目的だが、実機での確認は未実施（実機検証待ち）。
if [ -n "${WHILL_ROBOT_ID:-}" ] && [ -f "${WHILL_PLATFORM_CONFIG}/robots/${WHILL_ROBOT_ID}.yaml" ]; then
  _whill_domain="$(python3 -c "import sys,yaml;print(yaml.safe_load(open(sys.argv[1]))['ros_domain_id'])" \
    "${WHILL_PLATFORM_CONFIG}/robots/${WHILL_ROBOT_ID}.yaml" 2>/dev/null)"
  if [ -n "${_whill_domain}" ]; then
    export ROS_DOMAIN_ID="${_whill_domain}"
  fi
  unset _whill_domain
fi

unset _whill_env_src
