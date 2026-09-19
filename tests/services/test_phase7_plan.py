"""Phase 7 の計画と点検票が、実在するものを指し、互いに食い違わないこと。

計画（`docs/phase7-plan.md`）も点検票（`docs/phase7-checklist.md`）も、実機が
来るまで**誰も実行しない**。参照先が消えても、片方だけ直しても気づけない。

**当日は点検票だけを見る。** だから点検票の側に抜けがあってはいけない:
実機検証待ち（open-questions の B 節）の項目が、どこかの段に必ず 1 回だけ出ること。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'docs' / 'phase7-plan.md'
CHECKLIST = ROOT / 'docs' / 'phase7-checklist.md'


def hardware_items() -> list[str]:
    """open-questions の B 節（実機検証待ち）の行。"""
    text = (ROOT / 'docs' / 'open-questions.md').read_text('utf-8')
    section = text[text.index('## B.'):text.index('## C.')]
    return [line for line in section.splitlines() if line.startswith('| ')][1:]


def plan_allocation() -> dict[str, set[int]]:
    """計画 §5 の割り当て表: 段 → 項目番号。"""
    plan = PLAN.read_text('utf-8')
    table = plan[plan.index('## 5. 実機検証待ち'):plan.index('## 6. リスク')]
    allocation: dict[str, set[int]] = {}
    for line in table.splitlines():
        if not line.startswith('| ') or line.startswith('| 段') or set(line) <= set('|- '):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        # 「6 反映 200 ms の再測定」の 200 を拾わない。各項目の**先頭**の数字だけ。
        allocation[cells[0]] = {int(m.group(1)) for m in
                                (re.match(r'\s*(\d+)\s', part) for part in cells[1].split('、'))
                                if m}
    return allocation


def checklist_allocation() -> dict[str, set[int]]:
    """点検票の各段が「消える実機検証待ち」として挙げている番号。"""
    text = CHECKLIST.read_text('utf-8')
    found: dict[str, set[int]] = {}
    stage = None
    for line in text.splitlines():
        heading = re.match(r'^## 段 (\d+)', line)
        if heading:
            stage = heading.group(1)
        marker = re.match(r'^消える実機検証待ち: (.+)$', line)
        if marker and stage is not None:
            found[stage] = {int(n) for n in re.findall(r'\d+', marker.group(1))}
    return found


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


# ---- 点検票 -----------------------------------------------------------------


def test_checklist_exists_and_is_linked_from_the_plan_and_runbook():
    assert CHECKLIST.is_file()
    assert 'phase7-checklist.md' in PLAN.read_text('utf-8')
    assert 'phase7-checklist.md' in (ROOT / 'docs' / 'runbook.md').read_text('utf-8')


def test_checklist_has_the_same_stages_as_the_plan():
    plan_stages = {s for s in plan_allocation() if s.isdigit()}
    assert set(checklist_allocation()) == plan_stages


def test_checklist_and_plan_assign_the_same_items():
    """片方だけ直すと、当日に落ちる項目が出る。"""
    plan = {k: v for k, v in plan_allocation().items() if k.isdigit()}
    assert checklist_allocation() == plan


def test_every_hardware_item_appears_exactly_once_in_the_checklist():
    """**当日は点検票しか見ない。** どの段にも出てこない項目を残さない。

    段に割り当てられない項目（別の機会に消すもの）は、計画の「別」の行に置く。
    """
    assigned: list[int] = []
    for numbers in checklist_allocation().values():
        assigned.extend(numbers)
    deferred = plan_allocation().get('別', set())
    covered = sorted(set(assigned) | deferred)
    assert sorted(assigned) == sorted(set(assigned)), '同じ項目が 2 つの段にある'
    assert covered == list(range(1, len(hardware_items()) + 1)), (
        f'点検票に出てこない項目がある: '
        f'{sorted(set(range(1, len(hardware_items()) + 1)) - set(covered))}')


def test_each_stage_says_when_to_stop():
    """**進んでよい条件が無い段を作らない。** 迷ったときに進んでしまう。"""
    text = CHECKLIST.read_text('utf-8')
    stages = re.split(r'^## 段 ', text, flags=re.M)[1:]
    for stage in stages:
        number = stage.split(' ', 1)[0]
        assert '進んでよい条件' in stage, f'段 {number} に進んでよい条件が無い'


def test_the_stop_stage_refuses_a_retry():
    """段 1 は「もう一度だけ」をやらないと明記してあること。"""
    text = CHECKLIST.read_text('utf-8')
    stage1 = text[text.index('## 段 1'):text.index('## 段 2')]
    assert '中止条件' in stage1
    assert 'もう一度だけ' in stage1


def test_commands_in_the_checklist_exist():
    """打つコマンドが実在すること（`whill` のサブコマンド）。"""
    from whill_cli.main import app

    def name_of(command) -> str:
        return command.name or command.callback.__name__.replace('_', '-')

    names = {name_of(c) for c in app.registered_commands}
    for group in app.registered_groups:
        names |= {f'{group.name} {name_of(c)}'
                  for c in group.typer_instance.registered_commands}
    text = CHECKLIST.read_text('utf-8')
    used = set(re.findall(r'^whill ([a-z]+(?: [a-z]+)?)', text, flags=re.M))
    unknown = {u for u in used if u not in names and u.split()[0] not in names}
    assert unknown == set(), f'点検票が知らないコマンドを案内している: {sorted(unknown)}'


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


def test_real_mode_is_wired_but_marked_unverified():
    """配線しても「実機で動いたつもり」にしない（#77）。

    計画と launch の両方に「実機では起動していない」と書いてあること。
    実機で起動したら、両方を書き換える。
    """
    launch = (ROOT / 'ros' / 'src' / 'whill_bringup' / 'launch' /
              'bringup_launch.py').read_text('utf-8')
    assert 'mode=real はまだ配線していない' not in launch
    assert '実機では起動確認をしていない' in launch
    assert '実機では起動していない' in PLAN.read_text('utf-8')


def test_modes_the_plan_talks_about_exist():
    base = yaml.safe_load((ROOT / 'config' / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
    assert {'real', 'sim', 'mock', 'replay'} <= set(base['modes'])
