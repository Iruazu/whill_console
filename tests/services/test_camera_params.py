"""カメラのパラメータ名が実ドライバと一致していること（#53）。

**名前が食い違うと、mock では動くのに実機では「知らないパラメータ」になる。**
しかも黙って無視されるので、スライダーを動かしても何も起きない画面ができる。

突き合わせる相手は 3 つ:

  1. `config/params.yaml`（画面に出る宣言）
  2. `mock_realsense`（実機なしで動かす側）
  3. 実ドライバ `realsense2_camera` の `rs_launch.py`（**正**。手元にあるときだけ）
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PARAMS = ROOT / 'config' / 'params.yaml'
MOCK = ROOT / 'ros' / 'src' / 'whill_mock_drivers' / 'whill_mock_drivers' / 'mock_realsense.py'
RS_LAUNCH = Path.home() / ('whill_lab0_ros2/src/third_party/realsense-ros/'
                           'realsense2_camera/launch/rs_launch.py')

CAMERA_NODE = 'camera'


def camera_params() -> dict[str, dict]:
    data = yaml.safe_load(PARAMS.read_text('utf-8'))
    return {p['name']: p for p in data['params'] if p['node'] == CAMERA_NODE}


def mock_declared() -> set[str]:
    """`declare_parameter('...')` の第 1 引数を集める。import せずに読む
    （cv2 が要るので、CI の ros-base では import できない）。"""
    tree = ast.parse(MOCK.read_text('utf-8'))
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'declare_parameter' and node.args
                and isinstance(node.args[0], ast.Constant)):
            names.add(node.args[0].value)
    return names


def test_camera_params_are_registered():
    """登録が無いと、gateway は introspection しようがない（スライダーが出ない）。"""
    params = camera_params()
    assert set(params) >= {
        'rgb_camera.color_profile',
        'rgb_camera.enable_auto_exposure',
        'rgb_camera.exposure',
    }


def test_mock_declares_the_same_names():
    declared = mock_declared()
    missing = set(camera_params()) - declared
    assert missing == set(), f'mock が宣言していない: {sorted(missing)}'


# 実ドライバのパラメータには出どころが 2 つある。**同じ扱いにはできない。**
#
#   1. launch で宣言されるもの（rs_launch.py に名前がある）
#   2. **起動時にセンサの option から生えるもの。** 実ドライバは
#      `<module_name>.<option 名を小文字にしたもの>` という名前で declare する
#      （ros_sensor.cpp / sensor_params.cpp）。module_name はデバイスが名乗る
#      センサ名由来（"RGB Camera" → rgb_camera）。**その機体がその option を
#      持っているかはデバイス次第**なので、ソースを読んでも存在は確定できない。
LAUNCH_DECLARED = {'rgb_camera.color_profile', 'rgb_camera.enable_auto_exposure'}
SENSOR_OPTION = {'rgb_camera.exposure'}


@pytest.mark.skipif(not RS_LAUNCH.is_file(), reason=f'実ドライバが無い: {RS_LAUNCH}')
def test_launch_declared_names_match_the_real_driver():
    """実ドライバ側が名前を変えたら、ここで気づく。"""
    text = RS_LAUNCH.read_text('utf-8')
    declared = set(re.findall(r"'name':\s*'([^']+)'", text))
    unknown = LAUNCH_DECLARED - declared
    assert unknown == set(), (
        f'rs_launch.py に無い名前を params.yaml に書いている: {sorted(unknown)}')


def test_every_camera_param_is_accounted_for():
    """params.yaml に足したのに、どちら由来か分類していない名前を残さない。"""
    assert set(camera_params()) == LAUNCH_DECLARED | SENSOR_OPTION


@pytest.mark.skipif(not RS_LAUNCH.is_file(), reason=f'実ドライバが無い: {RS_LAUNCH}')
def test_sensor_option_names_follow_the_drivers_rule():
    """option 由来の名前が、ドライバの組み立て規則と矛盾していないこと。

    **存在の保証にはならない。** 規則（module 名 + option 名）と、module 名が
    rgb_camera であることまでしか確かめられない。実機で `ros2 param list` を
    見るまでは未確認（docs/open-questions.md）。
    """
    launch_text = RS_LAUNCH.read_text('utf-8')
    modules = {name.split('.')[0] for name in re.findall(r"'name':\s*'([^']+)'", launch_text)}
    for name in SENSOR_OPTION:
        module, _, option = name.partition('.')
        assert module in modules, f'{module} は実ドライバに出てこない module 名'
        assert option and option == option.lower()


def test_node_alias_points_at_the_real_node():
    """realsense2_camera は camera_namespace / camera_name とも既定 camera。"""
    data = yaml.safe_load(PARAMS.read_text('utf-8'))
    assert data['node_aliases'][CAMERA_NODE] == '/camera/camera'

    base = yaml.safe_load((ROOT / 'config' / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
    assert base['drivers']['realsense']['ros_node'] == '/camera/camera'


def test_unverified_parameters_are_not_live():
    """分からないものは live: false にしておく（実機で probe を通してから変える）。

    解像度の変更がストリーム再起動を伴うかは実機でしか確かめられない。
    live: true にしておくと、走行中に触れてしまう。
    """
    assert camera_params()['rgb_camera.color_profile']['live'] is False


def test_camera_is_not_a_nav2_input():
    """costmap は LiDAR。カメラは Nav2 に効かないので safety_class は none。

    sam_infer（#54）がカメラを入力にするなら、ここを見直すこと。
    """
    for name, spec in camera_params().items():
        assert spec['safety_class'] == 'none', name
