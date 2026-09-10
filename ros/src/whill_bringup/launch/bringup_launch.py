"""whill_platform の統合 bringup。real / sim / replay / mock を 1 本で扱う。

モードごとに別 launch を作らないのは、上位（gateway, Web UI）から見た構成が
モード間で食い違うと「mock では動くが実機で動かない」を作り込むため。
差分はドライバ層と時刻源（use_sim_time）だけに閉じる。

Nav2 のパラメータは whill_params が config/ から生成したものを使う。生成は
launch 時にその場で行う（LaunchConfiguration をパス解決に使わず、
launch description 生成時に確定させる — 既存リポで踏んだ罠を避ける）。
"""

import os
import subprocess
import tempfile
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

VALID_MODES = ('real', 'sim', 'replay', 'mock')


def _config_root() -> Path:
    env = os.environ.get('WHILL_PLATFORM_CONFIG')
    if env:
        return Path(env).expanduser()
    return Path(get_package_share_directory('whill_params')) / 'config'


def _load(path: Path) -> dict:
    with path.open(encoding='utf-8') as handle:
        return yaml.safe_load(handle)


def _require_existing_stack(package: str) -> str:
    """既存スタック (whill_lab0_ros2) のパッケージ share を返す。

    見つからないときに黙ってスキップしない。EKF が居ないと odom -> base_link が
    誰も出さず、Nav2 は「TF ツリーが 2 つに分かれている」と言い続けて
    永久に activate 待ちになる。原因が分かりにくい壊れ方なので、
    ここで止めて何を source すべきかを言う。
    """
    try:
        return get_package_share_directory(package)
    except Exception as exc:  # noqa: BLE001 - PackageNotFoundError も含めて拾う
        raise RuntimeError(
            f'{package} が見つからない。既存スタックを source すること: '
            f'source ~/whill_lab0_ros2/install/setup.bash '
            f'(通常は scripts/env.sh がやる)') from exc


def _nav2_params(robot_id: str, preset: str, use_sim_time: bool) -> str:
    """registry から Nav2 params を生成し、一時ファイルのパスを返す。

    生成に失敗したら例外を投げてそのまま落とす。既定値で静かに起動すると、
    UI のスライダーが指す値と実際に動いている値が食い違う（原則 3 違反）。
    """
    from whill_params import registry as reg
    from whill_params.generate_nav2_params import render

    template = Path(
        os.environ.get('WHILL_NAV2_TEMPLATE',
                       '~/whill_lab0_ros2/src/whill_navigation/config/nav2_params.yaml')
    ).expanduser()

    if template.is_file():
        text, unmapped = render(robot_id, template, preset or None)
        for key in unmapped:
            print(f'[whill_bringup] 警告: テンプレートに該当パスが無い: {key}')
        params = yaml.safe_load(text)
    else:
        # 既存スタックが無い環境（CI 等）では registry のネスト辞書だけで組む。
        # Nav2 の定型部分は nav2_bringup の既定に任せる。
        print(f'[whill_bringup] テンプレートが無いので registry のみで生成: {template}')
        registry = reg.load(robot_id, preset=preset or None)
        params = {node: {'ros__parameters': values}
                  for node, values in registry.as_nested().items()}

    # use_sim_time は registry の管轄外（モードで決まる実行時の性質）。
    # costmap は `local_costmap: local_costmap: ros__parameters:` と二重に
    # 入れ子になるので、一段しか見ないと costmap だけ use_sim_time が入らない。
    # mock (false) では既定値と一致して気づかないが、replay (true) で
    # costmap だけが実時刻を見る壊れ方をする。
    from whill_params.generate_nav2_params import iter_ros_parameters
    for block in iter_ros_parameters(params):
        block['use_sim_time'] = use_sim_time

    handle = tempfile.NamedTemporaryFile(
        mode='w', suffix=f'-{robot_id}-nav2.yaml', prefix='whill-', delete=False,
        encoding='utf-8')
    yaml.safe_dump(params, handle, allow_unicode=True, sort_keys=False)
    handle.close()
    print(f'[whill_bringup] Nav2 params を生成: {handle.name}')
    return handle.name


def _static_tf_nodes(robot: dict, use_sim_time: bool) -> list:
    """個体 yaml の tf_static をそのまま static_transform_publisher にする。

    URDF ではなく static TF なのは Phase 0 の割り切り。センサ位置の単一ソースを
    config/ に置くことを優先した。URDF 化（robot_state_publisher）は
    既存リポの Phase A の資産を移植する形で後続フェーズで行う。
    """
    nodes = []
    for child, entry in (robot.get('tf_static') or {}).items():
        xyz = [str(v) for v in entry['xyz']]
        rpy = [str(v) for v in entry['rpy']]
        nodes.append(Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name=f'static_tf_{child}',
            output='log',
            arguments=['--x', xyz[0], '--y', xyz[1], '--z', xyz[2],
                       '--roll', rpy[0], '--pitch', rpy[1], '--yaw', rpy[2],
                       '--frame-id', entry['parent'], '--child-frame-id', child],
            parameters=[{'use_sim_time': use_sim_time}],
        ))
    return nodes


def _setup(context, *args, **kwargs):
    robot_id = LaunchConfiguration('robot_id').perform(context)
    mode = LaunchConfiguration('mode').perform(context)
    preset = LaunchConfiguration('preset').perform(context)
    use_camera = LaunchConfiguration('use_camera').perform(context)
    bag = LaunchConfiguration('bag').perform(context)
    autostart = LaunchConfiguration('autostart').perform(context).lower() == 'true'
    start_gateway = LaunchConfiguration('gateway').perform(context).lower() == 'true'

    if mode not in VALID_MODES:
        raise RuntimeError(f'mode は {VALID_MODES} のいずれか。受け取った値: {mode}')

    root = _config_root()
    base = _load(root / 'robots' / 'cr2-base.yaml')
    robot = _load(root / 'robots' / f'{robot_id}.yaml')
    mode_decl = (base.get('modes') or {}).get(mode)
    if mode_decl is None:
        raise RuntimeError(f'cr2-base.yaml に modes.{mode} の宣言が無い')

    use_sim_time = bool(mode_decl.get('use_sim_time', False))
    actions = []

    # ---- ドライバ層 --------------------------------------------------------
    if mode == 'mock':
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory('whill_mock_drivers'),
                'launch', 'mock_drivers_launch.py')),
            launch_arguments={'robot_id': robot_id, 'mode': mode,
                              'use_camera': use_camera}.items(),
        ))
    elif mode == 'replay':
        if not bag:
            raise RuntimeError('mode=replay には bag:=<path> が必要')
        bag_path = Path(bag).expanduser()
        if not bag_path.exists():
            raise RuntimeError(f'bag が見つからない: {bag_path}')
        # --loop は使わない。ループすると /clock が巻き戻り、costmap の seq
        # 判定やテレメトリの「古さ」判定が壊れる。もう一度見たければ
        # 起動し直す（ADR-0004）。
        actions.append(ExecuteProcess(
            cmd=['ros2', 'bag', 'play', str(bag_path), '--clock'],
            output='screen'))
    elif mode == 'real':
        # 実機ドライバの include は実機復帰後に配線する。ここで黙って
        # 何も起動しないと「実機モードで動いたつもり」になるので明示的に落とす。
        raise RuntimeError(
            'mode=real はまだ配線していない（実機が手元にないため検証できない）。'
            'docs/open-questions.md の実機検証待ちリストを参照')
    elif mode == 'sim':
        raise RuntimeError(
            'mode=sim はまだ配線していない（Phase 0 のスコープ外）。'
            'sim/ の world 整備後に有効化する')

    # ---- TF ----------------------------------------------------------------
    # replay では出さない。bag に /tf_static が入っているので、こちらからも
    # 出すと二重になる（ADR-0004）。
    if mode != 'replay':
        actions.extend(_static_tf_nodes(robot, use_sim_time))

    if mode == 'mock':
        # mock には localizer がいないので map -> odom を identity で固定する。
        # 実機ではこの TF は scan-to-map localizer が出す。両方が出すと
        # TF が二重になるため、mock 限定であることを名前で明示する。
        actions.append(Node(
            package='tf2_ros', executable='static_transform_publisher',
            name='mock_map_to_odom', output='log',
            arguments=['--frame-id', 'map', '--child-frame-id', 'odom'],
            parameters=[{'use_sim_time': use_sim_time}]))

        # odom -> base_link は既存スタックの EKF が唯一の publisher。mock でも
        # 同じ EKF を include する（モックが自分で TF を出すと実機と配線が変わり、
        # 「mock では通るが実機で落ちる」を作り込む）。EKF の入力 /whill/odom と
        # /imu/data_rep145 は、どちらもモックが宣言どおりに出している。
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                _require_existing_stack('whill_localization'),
                'launch', 'ekf_odom_launch.py')),
            launch_arguments={'use_sim_time': str(use_sim_time).lower()}.items(),
        ))

    # ---- 地図 --------------------------------------------------------------
    map_yaml = os.path.join(
        get_package_share_directory('whill_bringup'), 'config', 'mock_corridor.yaml')
    if mode == 'mock' and os.path.isfile(map_yaml):
        actions.append(Node(
            package='nav2_map_server', executable='map_server', name='map_server',
            output='screen',
            parameters=[{'yaml_filename': map_yaml, 'use_sim_time': use_sim_time}]))
        actions.append(Node(
            package='nav2_lifecycle_manager', executable='lifecycle_manager',
            name='lifecycle_manager_map', output='screen',
            parameters=[{'autostart': autostart, 'use_sim_time': use_sim_time,
                         'node_names': ['map_server']}]))

    # ---- Nav2 --------------------------------------------------------------
    if mode_decl.get('include_stack', True):
        params_file = _nav2_params(robot_id, preset, use_sim_time)
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory('nav2_bringup'),
                'launch', 'navigation_launch.py')),
            launch_arguments={
                'params_file': params_file,
                'use_sim_time': str(use_sim_time).lower(),
                'autostart': str(autostart).lower(),
            }.items(),
        ))

    # ---- 速度の調停 --------------------------------------------------------
    if mode == 'mock':
        # twist_mux を入れないと、gateway の手動操作と E-stop が下流に届かない。
        # Nav2 の velocity_smoother が出す /cmd_vel を誰も消費しないので、
        # 入れる前は mock の車体がそもそも動いていなかった。
        actions.append(Node(
            package='twist_mux', executable='twist_mux', name='twist_mux',
            output='screen',
            parameters=[
                os.path.join(get_package_share_directory('whill_bringup'),
                             'config', 'twist_mux_mock.yaml'),
                {'use_sim_time': use_sim_time},
            ],
            # 出力をモックドライバの入力へ。cr2-base.yaml の
            # whill_serial.subscribes と一致していること。
            remappings=[('cmd_vel_out', '/whill/controller/cmd_vel')],
        ))

    # ---- gateway -----------------------------------------------------------
    if start_gateway:
        actions.append(Node(
            package='whill_gateway', executable='gateway', name='whill_gateway',
            output='screen',
            # bag を渡すのは replay のときだけ。他モードで渡すと、gateway が
            # 再生していないのに再生位置を出そうとする。
            parameters=[{'robot_id': robot_id, 'mode': mode,
                         'use_sim_time': use_sim_time,
                         'bag': str(Path(bag).expanduser()) if mode == 'replay' else ''}]))

    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('robot_id', default_value='cr2-01',
                              description='個体 ID (cr2-01 / cr2-02 / cr2-03)'),
        DeclareLaunchArgument('mode', default_value='mock',
                              description=f'{" / ".join(VALID_MODES)}'),
        DeclareLaunchArgument('preset', default_value='',
                              description='config/presets/<name>.yaml を適用する'),
        DeclareLaunchArgument('use_camera', default_value='false',
                              description='realsense を追加で起動する'),
        DeclareLaunchArgument('bag', default_value='',
                              description='mode=replay のときの MCAP パス'),
        DeclareLaunchArgument('autostart', default_value='true',
                              description='Nav2 の lifecycle を自動で activate する'),
        DeclareLaunchArgument('gateway', default_value='false',
                              description='whill_gateway を同時に起動する。'
                                          'mode=replay では実質必須（bag を'
                                          '見るための唯一の口）'),
        OpaqueFunction(function=_setup),
    ])
