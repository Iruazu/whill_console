#!/usr/bin/env bash
# rosbag2 の sqlite3 (.db3) 記録を MCAP に変換する。
#
#   ./scripts/convert_bag_to_mcap.sh <入力bagディレクトリ> [出力名]
#
# 7〜8 月のキャンパス走行は既存リポの docs/m7-bench-data/ に .db3 で入っている
# (計 45 GB)。全部を変換する必要はない。replay の検証に使う代表 1 本だけを
# bags/ に置く。bags/ は .gitignore 済みなので、変換物はコミットされない。
#
# 冪等ではない: 出力先が既にあるときは何もせず終わる (上書きしない)。
set -eo pipefail

SRC="${1:?入力 bag ディレクトリを指定すること}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${2:-$(basename "${SRC}")}"
DEST="${ROOT}/bags/${NAME}"

if [ ! -f "${SRC}/metadata.yaml" ]; then
  echo "rosbag2 の記録ではない (metadata.yaml が無い): ${SRC}" >&2
  exit 2
fi

if [ -e "${DEST}" ]; then
  echo "既にある。消してから再実行すること: ${DEST}" >&2
  exit 0
fi

set +u
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
set -u

echo "変換: ${SRC} → ${DEST}"
ros2 bag convert \
  --input "${SRC}" sqlite3 \
  --output-options /dev/stdin <<YAML
output_bags:
  - uri: ${DEST}
    storage_id: mcap
    all: true
YAML

ros2 bag info "${DEST}"
