"""設計原則 1 の例外（stackd）が、認めた条件から外れていないこと（Q7）。

原則 1 は「ROS への口は gateway の WebSocket 1 本と ssh のみ」。**運用のための
`whill_stackd` (8770) だけを例外として認める**と決めた（2026-09-16）。認めた
条件は 3 つ:

  1. **ROS を喋らない**（DDS も topic も通さない）
  2. **LAN 限定**
  3. **gateway と同じトークンで認証する**

**例外は文言で認めただけでは守られない。** ここで機械的に検査する。条件から
外れたら、それは原則違反として扱う（例外の範囲が広がるのを防ぐ）。

ブラウザが開く WebSocket が 8765 と 8770 だけであることは
`web/tests/screenshots.spec.ts` が別に確かめている。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STACKD = ROOT / 'services' / 'whill_stackd'

ROS_MODULES = {'rclpy', 'rosidl_runtime_py', 'rosbag2_py', 'tf2_ros', 'ament_index_python',
               'geometry_msgs', 'sensor_msgs', 'nav_msgs', 'std_msgs', 'std_srvs',
               'diagnostic_msgs', 'rcl_interfaces', 'tf2_msgs', 'action_msgs',
               'map_msgs', 'rosgraph_msgs', 'whill_msgs', 'whill_params'}
"""これを import していたら「ROS を喋らない」が崩れている。"""


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text('utf-8'))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split('.')[0])
    return names


def test_stackd_does_not_speak_ros():
    """条件 1。ROS を喋り始めたら、それは 2 本目の ROS の口になる。"""
    offenders = {}
    for path in sorted(STACKD.rglob('*.py')):
        found = _imports(path) & ROS_MODULES
        if found:
            offenders[str(path.relative_to(ROOT))] = sorted(found)
    assert offenders == {}, f'stackd が ROS を import している: {offenders}'


def test_stackd_only_starts_the_stack_as_a_child_process():
    """stackd が ROS に触る唯一の形は「`whill run` を子プロセスで起動する」こと。"""
    supervisor = (STACKD / 'supervisor.py').read_text('utf-8')
    assert 'whill' in supervisor and 'subprocess' in supervisor


def test_stackd_uses_the_same_token_as_the_gateway():
    """条件 3。別のトークンを持つと、口が 2 つ・秘密も 2 つになる。"""
    main = (STACKD / 'main.py').read_text('utf-8')
    assert "os.environ.get('WHILL_GATEWAY_TOKEN'" in main
    # 無認証では起動しない（gateway と同じ規則）
    assert 'stackd は無認証では起動しない' in main


def test_stackd_refuses_a_short_token():
    main = (STACKD / 'main.py').read_text('utf-8')
    assert re.search(r'len\(token\)\s*<\s*8', main)


def test_stackd_is_lan_only_by_intent():
    """条件 2。既定の bind は LAN 向けで、外向けに晒す作りを持たないこと。"""
    main = (STACKD / 'main.py').read_text('utf-8')
    assert '--host' in main and 'LAN 限定' in main
    # UPnP やトンネルの類を持ち込んでいない
    for path in sorted(STACKD.rglob('*.py')):
        text = path.read_text('utf-8').lower()
        for forbidden in ('upnp', 'ngrok', 'localtunnel', 'cloudflared'):
            assert forbidden not in text, f'{path.name} に {forbidden}'


# ---- 文言そのもの -----------------------------------------------------------

PRINCIPLE_FILES = [ROOT / 'CLAUDE.md', ROOT / 'docs' / 'requirements.md']


def _principle_1(path: Path) -> str:
    text = path.read_text('utf-8')
    match = re.search(r'^1\. \*\*ROS は実機PC内に閉じる。\*\*(.+?)(?=^2\. )', text,
                      re.S | re.M)
    assert match, f'{path.name} に設計原則 1 が見つからない'
    return ' '.join(match.group(1).split())


@pytest.mark.parametrize('path', PRINCIPLE_FILES, ids=lambda p: p.name)
def test_principle_1_states_the_exception_and_its_conditions(path):
    """例外を認めるなら、**条件も一緒に書く。** 条件の無い例外は際限なく広がる。"""
    text = _principle_1(path)
    assert 'whill_stackd' in text
    assert 'ROS を喋らない' in text
    assert 'LAN 限定' in text
    assert 'トークン' in text


def test_the_two_copies_of_principle_1_stay_identical():
    """CLAUDE.md と requirements.md の原則 1 が食い違わないこと。

    却下の根拠が 2 つあって中身が違う、が一番まずい（Q7 がまさにそれだった）。
    """
    texts = {path.name: _principle_1(path) for path in PRINCIPLE_FILES}
    assert len(set(texts.values())) == 1, texts
