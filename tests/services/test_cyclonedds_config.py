"""CycloneDDS の設定が本リポのもので、想定どおりの形であること（K2）。

以前は既存リポ（`~/whill_lab0_ros2/configs/`）のファイルにフォールバックしていた。
**こちらで管理していないファイルに挙動が依存**し、しかもそこに書かれた
USB-Ethernet の名前はドック交換で古くなっていた。

ここで見るのは 3 つ:

  1. `scripts/env.sh` が本リポの設定を指すこと（既存リポに戻らないこと）
  2. 許可列挙で、既定は lo だけ（設計原則 1: ROS は実機PC内に閉じる）
  3. 環境変数の既定値が「存在しない名前」であること。**空に展開されると
     Cyclone がドメイン生成ごと失敗する**（実測）
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config' / 'cyclonedds-runtime.xml'
ENV_SH = ROOT / 'scripts' / 'env.sh'
NS = {'c': 'https://cdds.io/config'}

INTERFACE_ENV = 'WHILL_DDS_INTERFACE'


def interfaces() -> list[dict[str, str]]:
    tree = ET.parse(CONFIG)
    return [entry.attrib for entry in tree.getroot().iterfind(
        './/c:Interfaces/c:NetworkInterface', NS)]


def test_env_sh_points_at_this_repo():
    text = ENV_SH.read_text('utf-8')
    assert 'CYCLONEDDS_URI="file://${WHILL_PLATFORM_ROOT}/config/cyclonedds-runtime.xml"' in text
    # 既存リポへのフォールバックを残さない（単一ソース）
    assert 'whill_lab0_ros2/configs/cyclonedds' not in text


def test_loopback_is_allowed_and_is_the_only_default():
    names = [entry['name'] for entry in interfaces()]
    assert 'lo' in names
    # lo 以外は環境変数で入れるものだけ。実 NIC の名前を焼き込まない
    # （MAC 由来なので、ドックやアダプタを替えると変わる）
    for name in names:
        assert name == 'lo' or name.startswith('${')


def test_optional_interface_has_a_non_empty_default():
    """空に展開されると `rmw_create_node: failed to create domain` で落ちる。"""
    entry = next(e for e in interfaces() if e['name'].startswith('${'))
    assert entry.get('presence_required') == 'false'
    match = re.fullmatch(r'\$\{' + INTERFACE_ENV + r':-([^}]+)\}', entry['name'])
    assert match, entry['name']
    assert match.group(1).strip(), '既定値が空。Cyclone がドメイン生成に失敗する'


def test_settings_the_existing_stack_removed_are_not_reintroduced():
    """既存リポが一度入れて外したもの。あちらの記録では data path を塞いでいた。"""
    text = CONFIG.read_text('utf-8')
    body = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    assert '<DontRoute>' not in body
    assert '<AllowMulticast>' not in body


def test_participant_index_covers_the_stack():
    """mock 構成でノードは 29 個。既定の 9 では足りない。"""
    root = ET.parse(CONFIG).getroot()
    assert int(root.find('.//c:Discovery/c:MaxAutoParticipantIndex', NS).text) >= 30


def test_config_is_valid_xml_with_the_cyclone_namespace():
    root = ET.parse(CONFIG).getroot()
    assert root.tag == '{https://cdds.io/config}CycloneDDS'
