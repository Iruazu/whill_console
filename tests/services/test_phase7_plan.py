"""Phase 7 の計画（`docs/phase7-plan.md`）が実在するものを指していること。

計画は実機が来るまで**誰も実行しない**ので、参照先が消えても気づけない。
パスとパッケージ名だけでも機械的に見ておく。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'docs' / 'phase7-plan.md'


def test_plan_exists_and_is_linked_from_requirements():
    assert PLAN.is_file()
    assert 'phase7-plan.md' in (ROOT / 'docs' / 'requirements.md').read_text('utf-8')


@pytest.mark.parametrize('relative', [
    'services/whill_stackd/whill-stackd.service',
    'docs/open-questions.md',
    'docs/measurements',
])
def test_paths_in_the_plan_exist(relative):
    assert (ROOT / relative).exists(), relative
    assert relative in PLAN.read_text('utf-8'), f'計画が {relative} に触れていない'


def test_plan_covers_every_hardware_item():
    """B 節（実機検証待ち）の件数と、計画の割り当て表の整合。

    **件数が増えたら計画を見直す。** 割り当てられていない項目があると、
    当日に「これはいつやるのか」を考えることになる。
    """
    text = (ROOT / 'docs' / 'open-questions.md').read_text('utf-8')
    section = text[text.index('## B.'):text.index('## C.')]
    items = [line for line in section.splitlines() if line.startswith('| ')][1:]
    plan = PLAN.read_text('utf-8')
    match = re.search(r'実機検証待ち (\d+) 件の割り当て', plan)
    assert match, '計画に割り当ての節が無い'
    assert int(match.group(1)) == len(items), (
        f'B 節は {len(items)} 件だが、計画は {match.group(1)} 件のつもりでいる')


def test_real_mode_is_still_unwired():
    """計画が前提にしている状態（mode=real は未配線）が変わっていないこと。"""
    launch = (ROOT / 'ros' / 'src' / 'whill_bringup' / 'launch' /
              'bringup_launch.py').read_text('utf-8')
    assert 'mode=real はまだ配線していない' in launch, \
        'mode=real を配線したなら、Phase 7 の計画（§3）を書き換えること'


def test_modes_the_plan_talks_about_exist():
    base = yaml.safe_load((ROOT / 'config' / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
    assert {'real', 'sim', 'mock', 'replay'} <= set(base['modes'])
