"""ROS の子プロセスに uv の venv を持ち込まないこと（K5 の sim で露見）。

`whill` は `uv run` で動くので PATH の先頭に venv の bin が入る。そのまま
`ros2 launch` に渡すと、`#!/usr/bin/env python3` の ROS スクリプトが venv の
python3 で動き、rclpy や lxml が無くて落ちる（sim の spawn_entity.py で実際に起きた）。
"""

from __future__ import annotations

import os
import shutil

from whill_cli.main import _ros_env, without_venv


def test_venv_bin_is_removed_and_order_is_kept():
    env = {
        'VIRTUAL_ENV': '/repo/services/.venv',
        'PATH': os.pathsep.join(['/repo/services/.venv/bin', '/opt/ros/humble/bin',
                                 '/usr/local/bin', '/usr/bin']),
        'ROS_DOMAIN_ID': '21',
    }
    result = without_venv(env)
    assert result['PATH'].split(os.pathsep) == ['/opt/ros/humble/bin', '/usr/local/bin', '/usr/bin']
    assert 'VIRTUAL_ENV' not in result
    assert result['ROS_DOMAIN_ID'] == '21'
    # 元の辞書は変えない
    assert env['VIRTUAL_ENV'] == '/repo/services/.venv'


def test_trailing_slash_is_also_removed():
    env = {'VIRTUAL_ENV': '/v', 'PATH': os.pathsep.join(['/v/bin/', '/usr/bin'])}
    assert without_venv(env)['PATH'] == '/usr/bin'


def test_without_a_venv_nothing_changes():
    env = {'PATH': '/usr/bin'}
    assert without_venv(env) == env


def test_python3_for_ros_is_not_the_venvs():
    """いま uv run の中で動いているこのテスト自身の環境で確かめる。"""
    venv = os.environ.get('VIRTUAL_ENV')
    env = _ros_env()
    found = shutil.which('python3', path=env['PATH'])
    if venv:
        assert found is None or not found.startswith(os.path.join(venv, 'bin'))
    assert 'VIRTUAL_ENV' not in env


def test_doctor_does_not_pass_when_there_is_nothing_to_check():
    """宣言が 0 件のモードで「0 件すべて publish されている」と合格にしない。

    replay は bag がトピックを出すのでドライバ宣言が無い。sim も以前はそうで、
    whill doctor が中身の無い合格を出していた。
    """
    from typer.testing import CliRunner

    from whill_cli.main import app

    result = CliRunner().invoke(app, ['doctor', '--robot', 'cr2-01', '--mode', 'replay'])
    assert result.exit_code == 1
    assert '判定していない' in result.output
