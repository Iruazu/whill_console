#!/usr/bin/env bash
# PR にレビューを依頼する（任意）。**自分の GitHub アカウントで**実行する。
#
#   scripts/request-review.sh <PR 番号> copilot
#   scripts/request-review.sh <PR 番号> devin
#
# ## 自動で回さない理由
#
# どちらも依頼した人のプランや利用枠を消費する。CI の bot から依頼しても、
# あなたのプランは使えない（そもそも依頼できないか、別途課金が要る）。
# 必要なときだけ自分で依頼する。
#
# ## 前提（2026-09 時点で調べたもの。変わりうる）
#
# copilot  Copilot のプランが要る。**Copilot Free には含まれない**（VS Code の
#          「Review selection」だけ）。Copilot Student（認証済みの学生は無料）、
#          Pro 以上に含まれる。2026-06 から GitHub Actions の分数も消費する。
#          https://docs.github.com/en/copilot/get-started/plans
# devin    Devin のアカウントと、この repo（private）に Devin の GitHub App が
#          入っている必要がある。レビューは ACU を消費する。
#          https://docs.devin.ai/work-with-devin/devin-review
set -euo pipefail

if [ $# -ne 2 ]; then
  sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

pr="$1"; who="$2"
case "${pr}" in
  ''|*[!0-9]*) echo "PR 番号が数字でない: ${pr}" >&2; exit 2 ;;
esac

case "${who}" in
  copilot)
    gh pr edit "${pr}" --add-reviewer @copilot
    echo "PR #${pr} に Copilot のレビューを依頼した。結果は PR のレビュー欄に出る。"
    echo "失敗した場合は、自分のアカウントの Copilot のプランを確認すること。"
    ;;
  devin)
    gh pr comment "${pr}" --body '/devin review'
    echo "PR #${pr} に /devin review とコメントした。"
    echo "反応が無い場合は、Devin の GitHub App がこの repo に入っているか確認すること。"
    ;;
  *)
    echo "copilot か devin を指定すること（受け取った値: ${who}）" >&2
    exit 2
    ;;
esac
