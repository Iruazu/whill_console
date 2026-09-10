#!/usr/bin/env bash
# 全テストを走らせる。CI 相当。冪等。
#
#   ./scripts/test.sh          全部
#   ./scripts/test.sh ros      colcon ws の pytest だけ
#   ./scripts/test.sh services CLI / config の pytest だけ
#   ./scripts/test.sh web      vitest + Playwright スクリーンショット
set -eo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# ROS の setup.bash は未定義変数を参照するので、source の間だけ -u を外す。
set +u
# shellcheck disable=SC1091
source "${ROOT}/scripts/env.sh"
set -u

# ROS を source した shell では pytest が ROS 製プラグイン (launch_pytest 等) を
# 自動 load しようとし、uv の venv に無い lark を要求して collection 前に落ちる。
# ini の `-p no:` は load の後に読まれるので効かない。環境変数だけが効く。
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

target="${1:-all}"
failed=0

run() {
  echo "── $1 ─────────────────────────────────────────"
  shift
  if ! "$@"; then
    failed=1
    echo "  → 失敗"
  fi
}

if [ "$target" = "all" ] || [ "$target" = "services" ]; then
  run "services (config / CLI)" \
    env -C "${ROOT}/services" uv run pytest "${ROOT}/tests/services" -q
  # CI と同じ規則で lint する。ローカルで緑なのに CI で赤い、を作らない。
  run "services (lint)" \
    env -C "${ROOT}/services" uv run ruff check .
fi

if [ "$target" = "all" ] || [ "$target" = "ros" ]; then
  # whill_params と rcl_interfaces は colcon ws / ROS から来るので、uv の venv では
  # なくシステム python3 で走らせる。env.sh が両方 source 済み。
  # -rs: skip された理由を出す。既存スタックが無い環境で全部 skip されて
  # 緑になるのを見逃さないため。
  run "ros (registry / descriptors)" \
    python3 -m pytest "${ROOT}/tests/ros" -q -rs
fi

if [ "$target" = "all" ] || [ "$target" = "web" ]; then
  run "web (typecheck)" env -C "${ROOT}/web" pnpm exec tsc -b
  run "web (vitest)" env -C "${ROOT}/web" pnpm exec vitest run
  run "web (playwright スクリーンショット)" env -C "${ROOT}/web" pnpm exec playwright test
fi

if [ "$failed" -ne 0 ]; then
  echo "失敗あり"
  exit 1
fi
echo "全て通過"
