"""個体 yaml の tf_static が、既存スタックの実配線と一致していること。

**既存スタック（`~/whill_lab0_ros2`）が正。** あちらが実車を走らせているので、
食い違ったら本リポ側のバグ（CLAUDE.md「既存スタックとの関係」）。

#51 の tf パネルを入れたときに、cr2-01.yaml が実機と 3 か所ずれていたのが
分かった（camera_link の親が違う／IMU と LiDAR の値が noetic 時代のまま／
誰も publish していない base_footprint を宣言していた）。**宣言だけ見ていても
気づけないので、実配線と突き合わせる。**

既存リポが無い環境（CI）では skip する。
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
STATIC_TF = (Path.home() / 'whill_lab0_ros2' / 'src' / 'whill_sensors_bringup' /
             'launch' / 'static_tf_launch.py')

TOLERANCE_M = 1e-6
TOLERANCE_RAD = 1e-6


def existing_stack_transforms() -> dict[str, dict]:
    """`_static_tf(name, x, y, z, roll, pitch, yaw, parent, child)` を読む。"""
    tree = ast.parse(STATIC_TF.read_text('utf-8'))
    found: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == '_static_tf' and len(node.args) == 9):
            continue
        values = [ast.literal_eval(arg) for arg in node.args[1:]]
        x, y, z, roll, pitch, yaw, parent, child = values
        found[child] = {'parent': parent, 'xyz': [x, y, z], 'rpy': [roll, pitch, yaw]}
    assert found, f'{STATIC_TF} から static TF を読めなかった（書式が変わった？）'
    return found


@pytest.mark.skipif(not STATIC_TF.is_file(), reason=f'既存スタックが無い: {STATIC_TF}')
def test_cr2_01_matches_the_existing_stack():
    real = existing_stack_transforms()
    ours = yaml.safe_load((ROOT / 'config' / 'robots' / 'cr2-01.yaml').read_text('utf-8'))
    tf = ours['tf_static']

    assert set(tf) == set(real), (
        f'フレームの顔ぶれが違う。yaml={sorted(tf)} 既存スタック={sorted(real)}')

    for child, expected in real.items():
        entry = tf[child]
        assert entry['parent'] == expected['parent'], f'{child} の親が違う'
        for axis, (got, want) in enumerate(zip(entry['xyz'], expected['xyz'])):
            assert math.isclose(got, want, abs_tol=TOLERANCE_M), \
                f'{child} の xyz[{axis}]: yaml {got} / 既存スタック {want}'
        for axis, (got, want) in enumerate(zip(entry['rpy'], expected['rpy'])):
            assert math.isclose(got, want, abs_tol=TOLERANCE_RAD), \
                f'{child} の rpy[{axis}]: yaml {got} / 既存スタック {want}'


@pytest.mark.skipif(not STATIC_TF.is_file(), reason=f'既存スタックが無い: {STATIC_TF}')
def test_no_frame_that_nobody_publishes():
    """既存スタックが出さないフレームを宣言しない。

    base_footprint がそうだった。誰も publish しないので、tf パネルは毎回
    「来ていない」と出し、Nav2 も robot_base_frame に base_link を使っている。
    """
    real = existing_stack_transforms()
    for robot in ('cr2-01', 'cr2-02', 'cr2-03'):
        tf = yaml.safe_load(
            (ROOT / 'config' / 'robots' / f'{robot}.yaml').read_text('utf-8'))['tf_static']
        extra = set(tf) - set(real)
        assert extra == set(), f'{robot}: 誰も publish しないフレーム {sorted(extra)}'


def test_camera_hangs_off_base_link_not_the_lidar():
    """親を間違えると、カメラの位置が LiDAR の分だけずれる。

    既存リポが無い環境でも見たいので、値ではなく形だけ確かめる。
    """
    for robot in ('cr2-01', 'cr2-02', 'cr2-03'):
        tf = yaml.safe_load(
            (ROOT / 'config' / 'robots' / f'{robot}.yaml').read_text('utf-8'))['tf_static']
        assert tf['camera_link']['parent'] == 'base_link', robot
