"""runbook に書いたパラメータ名・ファイル名が実在すること。

**手順書が嘘をつくのが一番たちが悪い。** 現場で打ってから違うと分かる。
キーを改名したときに気づけるよう、機械的に突き合わせる。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / 'docs' / 'runbook.md'


def registry_keys() -> set[str]:
    data = yaml.safe_load((ROOT / 'config' / 'params.yaml').read_text('utf-8'))
    return {f'{p["node"]}.{p["name"]}' for p in data['params']}


def backticked() -> list[str]:
    return re.findall(r'`([^`\n]+)`', RUNBOOK.read_text('utf-8'))


def test_parameter_keys_in_the_runbook_exist():
    keys = registry_keys()
    nodes = {key.split('.')[0] for key in keys}
    mentioned = {
        text for text in backticked()
        # ノード名で始まり、記号を含まない「キーらしいもの」だけ見る
        if '.' in text and text.split('.')[0] in nodes
        and re.fullmatch(r'[A-Za-z0-9_.]+', text)
    }
    assert mentioned, 'runbook がパラメータに一切触れていない（抽出が壊れた？）'
    unknown = mentioned - keys
    assert unknown == set(), f'runbook が存在しないパラメータを案内している: {sorted(unknown)}'


@pytest.mark.parametrize('relative', [
    'config/robots/cr2-base.yaml',
    'config/params.yaml',
    'docs/measurements/2026-09-14-tf-intervals.md',
    'docs/open-questions.md',
])
def test_files_the_runbook_points_at_exist(relative):
    """runbook が案内する先が消えていないこと。"""
    assert (ROOT / relative).is_file(), relative
    assert relative in RUNBOOK.read_text('utf-8'), f'runbook が {relative} に触れていない'
