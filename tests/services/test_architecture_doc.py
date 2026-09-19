"""アーキテクチャ図（`docs/architecture.md`）が実態とずれていないこと。

**図は放っておくと必ず古くなる。** 全部は機械で見られないが、「モードごとに何が
起動するか」「口はいくつか」「トピック名」くらいは設定と突き合わせられる。

ここが落ちたら、図を直すか、図が正しくて実装が変わったのかを確かめること。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs' / 'architecture.md'
BASE = yaml.safe_load((ROOT / 'config' / 'robots' / 'cr2-base.yaml').read_text('utf-8'))


def text() -> str:
    return DOC.read_text('utf-8')


def test_doc_exists_and_is_linked():
    assert DOC.is_file()
    assert 'architecture.md' in (ROOT / 'CLAUDE.md').read_text('utf-8') or \
        'architecture.md' in (ROOT / 'docs' / 'requirements.md').read_text('utf-8')


def test_every_mode_is_in_the_table():
    """モードを足したら図も直す。"""
    doc = text()
    for mode in BASE['modes']:
        assert re.search(rf'\b{mode}\b', doc), f'図に {mode} が無い'


def test_topics_named_in_the_doc_exist_in_the_declaration():
    """図に書いたドライバのトピックが宣言にあること（名前を間違えない）。"""
    declared = {entry['topic']
                for decl in BASE['drivers'].values()
                for entry in (decl.get('publishes') or []) + (decl.get('subscribes') or [])}
    doc = text()
    for topic in ('/whill/odom', '/velodyne_points', '/imu/data_rep145',
                  '/whill/controller/cmd_vel'):
        assert topic in doc, f'図が {topic} に触れていない'
        assert topic in declared, f'{topic} が cr2-base.yaml の宣言に無い'


def test_ports_match_the_registry_and_stackd():
    """口の番号を図に書いている。実装とずれたら直す。"""
    params = yaml.safe_load((ROOT / 'config' / 'params.yaml').read_text('utf-8'))
    port = next(p['default'] for p in params['params']
                if p['node'] == 'whill_gateway' and p['name'] == 'port')
    stackd = (ROOT / 'services' / 'whill_stackd' / 'server.py').read_text('utf-8')
    stackd_port = int(re.search(r'DEFAULT_PORT = (\d+)', stackd).group(1))
    doc = text()
    assert str(port) in doc, f'gateway の {port} が図に無い'
    assert str(stackd_port) in doc, f'stackd の {stackd_port} が図に無い'


def test_protocol_message_types_are_all_listed():
    """プロトコルに型を足したら図も直す（画面に出る/出せるものの一覧なので）。"""
    protocol = (ROOT / 'ros' / 'src' / 'whill_gateway' / 'whill_gateway' /
                'protocol.py').read_text('utf-8')
    names = set(re.findall(r"^MSG_[A-Z_]+ = '([a-z_]+)'", protocol, flags=re.M))
    doc = text()
    missing = {name for name in names if f'`{name}`' not in doc}
    assert missing == set(), f'図に載っていないメッセージ型: {sorted(missing)}'


def test_diagrams_are_mermaid_blocks_and_balanced():
    doc = text()
    opens = len(re.findall(r'^```mermaid$', doc, flags=re.M))
    closes = len(re.findall(r'^```$', doc, flags=re.M))
    assert opens >= 5, '図が少なすぎる（中身が文章だけになっていないか）'
    assert closes == opens, 'mermaid ブロックが閉じていない'


@pytest.mark.parametrize('relative', [
    'ros/src/whill_bringup/launch/bringup_launch.py',
    'docs/open-questions.md',
    'docs/adr',
])
def test_paths_in_the_doc_exist(relative):
    assert (ROOT / relative).exists()
    assert relative in text(), f'図が {relative} に触れていない'
