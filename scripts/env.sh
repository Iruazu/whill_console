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

# CycloneDDS の設定。**本リポのものを使う**（K2）。以前は既存リポのファイルに
# フォールバックしていたが、こちらで管理していないファイルに挙動が依存し、
# 中の NIC 名も古くなっていた。中身の方針は config/cyclonedds-runtime.xml。
#
# 実機で LiDAR の有線 NIC も DDS に使うときは、起動前に名前を入れる:
#   export WHILL_DDS_INTERFACE=enx00e04c680ec9
# 設定を変えたら `ros2 daemon stop`（daemon が古い設定のまま残る）。
export CYCLONEDDS_URI="file://${WHILL_PLATFORM_ROOT}/config/cyclonedds-runtime.xml"

# 研究室 CA の証明書（#55）。発行済みなら gateway / stackd / 開発サーバは
# https・wss で待ち受け、CLI は wss で繋ぐ。iPad から開くのに要る。
# 平文で動かしたいときだけ WHILL_TLS=off を付けて source する。
_whill_tls_dir="${WHILL_TLS_DIR:-${HOME}/.config/whill/tls}"
if [ "${WHILL_TLS:-on}" = "off" ]; then
  # **既に入っている値を消す。** 同じシェルで先に（off 無しで）source していると、
  # 変数が残ったままになり「平文で上げたはずの gateway が wss で待ち受ける」。
  # live テスト（ブラウザは ws:// で繋ぐ）で実際に踏んだ。
  unset WHILL_TLS_CERT WHILL_TLS_KEY WHILL_TLS_CA
elif [ -f "${_whill_tls_dir}/server.crt" ] && [ -f "${_whill_tls_dir}/server.key" ]; then
  export WHILL_TLS_CERT="${_whill_tls_dir}/server.crt"
  export WHILL_TLS_KEY="${_whill_tls_dir}/server.key"
  export WHILL_TLS_CA="${_whill_tls_dir}/ca.crt"
fi
unset _whill_tls_dir

# ~/.local/bin (uv, node, pnpm) を通す
case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) ;;
  *) export PATH="${HOME}/.local/bin:${PATH}" ;;
esac

# `whill` / `whill-stackd` をそのまま叩けるようにする。中身は uv run の薄い入口。
# services/.venv/bin を足さないのは、venv の python3 がシステムの python3（ROS）を隠すから。
case ":${PATH}:" in
  *":${WHILL_PLATFORM_ROOT}/scripts/bin:"*) ;;
  *) export PATH="${WHILL_PLATFORM_ROOT}/scripts/bin:${PATH}" ;;
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
