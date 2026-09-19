#!/usr/bin/env bash
# 実 gateway に繋いで web の live テストを走らせる（起動 → 実行 → 停止）。
#
#   ./scripts/live-test.sh            mock と replay の両方
#   ./scripts/live-test.sh mock       mock だけ
#   ./scripts/live-test.sh replay     replay だけ
#
# なぜ要るか:
#   live テストは gateway が要るので**既定で skip** される。CI でも走らない。
#   手で起動する手順が長いと、書いたきり誰も走らせないテストになる。
#
# 何をするか:
#   - mock（または replay）のスタックを**平文**で上げる。ブラウザ（Playwright の
#     開発サーバは http）は ws:// で繋ぐので、wss だと接続できない
#   - live テストを走らせる
#   - 「gateway を落として上げ直すと再接続する」テストだけは、**裏でスタックを
#     再起動して**成立させる（gateway が死ぬと launch ごと落ちる設計 — #49）
#   - 自分が起動したものだけを止める
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8765
DOMAIN="${WHILL_LIVE_DOMAIN:-181}"
TOKEN="${WHILL_LIVE_TOKEN:-live-test-token}"
LOG_DIR="${WHILL_LIVE_LOG_DIR:-/tmp/whill-live-test}"
STACK_PID=""
TARGET="${1:-all}"

mkdir -p "${LOG_DIR}"

if [ "${TARGET}" != "all" ] && [ "${TARGET}" != "mock" ] && [ "${TARGET}" != "replay" ]; then
  echo "使い方: $0 [all|mock|replay]" >&2
  exit 2
fi

port_busy() {
  # **パイプで grep -q に渡さない。** grep が先に終了すると ss が SIGPIPE で
  # 落ち、pipefail のせいで「塞がっていない」と誤判定しうる。**塞がっているのに
  # 空きと読むと、動いているスタックを踏み潰す。**
  local listening
  listening=$(ss -ltn)
  case "${listening}" in
    *":${PORT} "*) return 0 ;;
    *) return 1 ;;
  esac
}

# **動いているスタックを止めない。** ブラウザ側の接続先は 8765 に固定なので、
# 塞がっていたら諦める（人が使っている最中かもしれない）。
if port_busy; then
  echo "port ${PORT} が塞がっている。動いているスタックを止めてから実行すること" >&2
  exit 1
fi

if [ ! -f "${ROOT}/ros/install/setup.bash" ]; then
  echo "ros/install が無い。先に colcon build すること" >&2
  exit 1
fi

set +u
# **平文で上げる。** WHILL_TLS=off は、既に入っている証明書のパスも消す（env.sh）。
export WHILL_TLS=off
# shellcheck disable=SC1091
source "${ROOT}/scripts/env.sh" >/dev/null 2>&1
set -u
export ROS_DOMAIN_ID="${DOMAIN}"
export WHILL_GATEWAY_TOKEN="${TOKEN}"

stop_stack() {
  [ -n "${STACK_PID}" ] || return 0
  kill -INT -"${STACK_PID}" 2>/dev/null
  for _ in $(seq 1 20); do
    kill -0 -"${STACK_PID}" 2>/dev/null || break
    sleep 1
  done
  pkill -9 -s "${STACK_PID}" 2>/dev/null
  STACK_PID=""
}

start_stack() {
  local mode="$1" extra=""
  if [ "${mode}" = replay ]; then
    extra="bag:=${ROOT}/bags/2026-07-31-campus"
    if [ ! -e "${ROOT}/bags/2026-07-31-campus" ]; then
      echo "bag が無い: ${ROOT}/bags/2026-07-31-campus（bags/README.md を見ること）" >&2
      return 1
    fi
  fi
  # shellcheck disable=SC2086
  setsid ros2 launch whill_bringup bringup_launch.py \
    robot_id:=cr2-01 mode:="${mode}" gateway:=true ${extra} \
    > "${LOG_DIR}/${mode}.log" 2>&1 &
  STACK_PID=$!
  for _ in $(seq 1 60); do
    grep -q '待ち受け中' "${LOG_DIR}/${mode}.log" && break
    sleep 1
  done
  if ! grep -q '待ち受け中' "${LOG_DIR}/${mode}.log"; then
    echo "gateway が上がらなかった: ${LOG_DIR}/${mode}.log" >&2
    return 1
  fi
  # 購読が揃うまで少し待つ（接続直後のスナップショットを見るテストがある）
  sleep 5

  # **Nav2 が active になるまで待つ。** 配車のテストは目標を投入して車体が動く
  # ことを見るので、Nav2 が上がりきる前に始めると落ちる（実際に落ちた）。
  # replay は Nav2 を起動しないので待たない（nav=not_started が正常）。
  if [ "${mode}" = replay ]; then
    return 0
  fi
  local status_text
  for _ in $(seq 1 40); do
    # **パイプで grep に渡さない。** `set -o pipefail` のもとで `grep -q` が
    # 先に終了すると whill tap が SIGPIPE で落ち、パイプライン全体が失敗に
    # なる。`nav=active` が出ているのに「上がらない」と判定して時間を溶かした。
    #
    # **COLUMNS を広げる。** tap の表示は rich なので、端末以外に出すと 80 桁で
    # 折り返し、`nav=active` が改行で割れる。
    status_text=$(COLUMNS=200 whill tap --port "${PORT}" --seconds 2 --stream status -v 2>/dev/null)
    case "${status_text}" in
      *nav=active*) return 0 ;;
    esac
    sleep 2
  done
  echo "Nav2 が active にならなかった: ${LOG_DIR}/${mode}.log" >&2
  return 1
}

trap stop_stack EXIT

play() {
  (cd "${ROOT}/web" && WHILL_LIVE=1 WHILL_LIVE_TOKEN="${TOKEN}" \
    pnpm exec playwright test "$@")
}

failed=0

run_mock() {
  # 起動に失敗しても、起動しかけたものは止める（残すと次の実行が別の
  # スタックに当たる。port を握ったままにもなる）。
  start_stack mock || { stop_stack; return 1; }
  play tests/live.spec.ts tests/live-params.spec.ts tests/live-dispatch.spec.ts \
       tests/live-drivers.spec.ts tests/live-obstacles.spec.ts tests/live-estop.spec.ts \
       --project=dev-desktop --grep-invert '再接続' || failed=1
  play tests/live-ops.spec.ts --project=ops-tablet || failed=1

  # 再接続のテストだけは、スタックを再起動して成立させる。
  # gateway だけを落とす選択肢は無い（落ちたら launch ごと止まる — #49）。
  #
  # **再起動は前面でやる。** サブシェルでやると STACK_PID が親に伝わらず、
  # 新しいスタックが追跡されないまま残る（最初の実装でそうなり、次の実行が
  # 別のトークンの gateway に当たって 2 件落ちた）。
  echo '── 再接続（途中でスタックを再起動する）─────────────────'
  play tests/live.spec.ts --project=dev-desktop --grep '再接続' &
  local test_pid=$!
  sleep 8
  stop_stack
  start_stack mock || failed=1
  wait "${test_pid}" || failed=1
  stop_stack
}

run_replay() {
  start_stack replay || { stop_stack; return 1; }
  play tests/live-replay.spec.ts --project=dev-desktop || failed=1
  stop_stack
}

if [ "${TARGET}" = all ] || [ "${TARGET}" = mock ]; then
  run_mock || failed=1
fi
if [ "${TARGET}" = all ] || [ "${TARGET}" = replay ]; then
  run_replay || failed=1
fi

# 自分が起動したものが残っていないこと。残すと次の実行が別のスタックに当たる。
if port_busy; then
  echo "port ${PORT} がまだ塞がっている。プロセスが残っている" >&2
  failed=1
fi

if [ "${failed}" -ne 0 ]; then
  echo "live テストに失敗がある（ログ: ${LOG_DIR}）" >&2
  exit 1
fi
echo "live テストは全部通った"
