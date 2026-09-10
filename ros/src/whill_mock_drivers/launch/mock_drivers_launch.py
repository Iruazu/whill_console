"""cr2-base.yaml の modes.<mode>.drivers 宣言に従ってモックを起動する。

どのモックを上げるかを launch にハードコードしない。宣言が唯一の正であり、
宣言を増やせば launch を触らずにモックが増える（CLAUDE.md 設計原則 3）。
"""

from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# mock_node 名から実行可能名への対応。cr2-base.yaml が持つのは mock_node だけで、
# ここが「宣言 → 実際に起動する実行ファイル」の唯一の対応表。
EXECUTABLES = {
    'mock_whill_serial': 'mock_whill_serial',
    'mock_velodyne': 'mock_velodyne',
    'mock_bno085': 'mock_bno085',
    'mock_realsense': 'mock_realsense',
}


def _config_root() -> Path:
    import os
    env = os.environ.get('WHILL_PLATFORM_CONFIG')
    if env:
        return Path(env).expanduser()
    return Path(get_package_share_directory('whill_params')) / 'config'


def _spawn(context, *args, **kwargs):
    robot_id = LaunchConfiguration('robot_id').perform(context)
    mode = LaunchConfiguration('mode').perform(context)
    use_camera = LaunchConfiguration('use_camera').perform(context).lower() == 'true'

    root = _config_root()
    with (root / 'robots' / 'cr2-base.yaml').open(encoding='utf-8') as handle:
        base = yaml.safe_load(handle)

    modes = base.get('modes') or {}
    if mode not in modes:
        raise RuntimeError(f'cr2-base.yaml に modes.{mode} の宣言が無い')

    wanted = list(modes[mode].get('drivers') or [])
    if use_camera and 'realsense' not in wanted:
        wanted.append('realsense')

    nodes = []
    for driver in wanted:
        declaration = (base.get('drivers') or {}).get(driver)
        if declaration is None:
            raise RuntimeError(f'cr2-base.yaml に drivers.{driver} の宣言が無い')
        mock_node = declaration.get('mock_node')
        executable = EXECUTABLES.get(mock_node)
        if executable is None:
            raise RuntimeError(f'{driver}: mock_node "{mock_node}" に対応する実行ファイルが無い')
        nodes.append(Node(
            package='whill_mock_drivers',
            executable=executable,
            name=mock_node,
            output='screen',
            parameters=[{'robot_id': robot_id}],
        ))
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('robot_id', default_value='cr2-01'),
        DeclareLaunchArgument('mode', default_value='mock'),
        DeclareLaunchArgument(
            'use_camera', default_value='false',
            description='realsense モックを追加で起動する。CPU を食うので既定は false'),
        OpaqueFunction(function=_spawn),
    ])
