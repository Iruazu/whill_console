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
    SetEnvironmentVariable,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from whill_bringup.gateway_guard import on_gateway_exit

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


def _waypoints_path(mode: str, robot: dict) -> str:
    """配車地点の yaml。

    mock は廊下地図に合わせた本リポの地点、real は個体 yaml の `maps.site` から
    既存リポの `docs/maps/<site>/waypoints.yaml` を引く。

    実機の地点をそのまま mock で使うと、キャンパスの座標が廊下地図の外を指して
    **全部 ABORTED になり、配線が壊れているのか地点が外なのか区別が付かない。**
    """
    if mode in ('mock', 'sim'):
        # sim の廊下は mock と同じ寸法なので、地点も同じものを使う。
        return os.path.join(
            get_package_share_directory('whill_bringup'),
            'config', 'mock_waypoints.yaml')

    maps = robot.get('maps') or {}
    entry = maps.get(maps.get('default')) or {}
    relative = entry.get('waypoints')
    if not relative:
        raise RuntimeError(
            '個体 yaml の maps.<default>.waypoints が無い。配車地点のパスを'
            '設定から引けない（ノード内にハードコードしないこと）')
    yaml_path = (Path(entry.get('source_repo', '~/whill_lab0_ros2')).expanduser()
                 / relative)
    if not yaml_path.is_file():
        # 空のまま起動すると「地点が 1 つも出ない配車パネル」になり、
        # 原因が分かりにくい。ここで止めてパスを言う。
        raise RuntimeError(f'配車地点が見つからない: {yaml_path}')
    return str(yaml_path)


def _repo_root() -> Path:
    """本リポの根。config/ の 1 つ上（WHILL_PLATFORM_CONFIG が指す）。"""
    return _config_root().parent


def _corridor_map_yaml(required: bool) -> str | None:
    """mock / sim 共通の廊下地図（scripts/make_mock_map.py の生成物、gitignore）。"""
    path = os.path.join(
        get_package_share_directory('whill_bringup'), 'config', 'mock_corridor.yaml')
    if os.path.isfile(path):
        return path
    if required:
        # sim は壁を物理で置くので、地図が無いと global costmap の static 層が
        # 空のまま Nav2 が経路を引けない。黙って進めず、作り方を言う。
        raise RuntimeError(
            f'廊下の地図が無い: {path}\n'
            f'  python3 scripts/make_mock_map.py && colcon build --packages-select whill_bringup')
    return None


def _sim_actions(robot: dict, base: dict, use_sim_time: bool) -> list:
    """Gazebo Classic 11 の起動と車体の投入（K5）。

    world と車体は起動のたびに config から生成する（whill_bringup/sim.py の
    docstring 参照 — 寸法とセンサ位置の単一ソースを守るため）。
    """
    import importlib.util

    from whill_bringup import sim as whill_sim

    sim_decl = base.get('sim')
    if not sim_decl:
        raise RuntimeError('cr2-base.yaml に sim の宣言が無い')

    # 廊下の寸法は mock の地図の生成器が正。
    spec = importlib.util.spec_from_file_location(
        'make_mock_map', _repo_root() / 'scripts' / 'make_mock_map.py')
    corridor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corridor)

    world = whill_sim.corridor_world_sdf(
        half_width=corridor.HALF_WIDTH, length=corridor.LENGTH,
        wall_thickness=corridor.WALL_THICKNESS,
        obstacle=(corridor.OBSTACLE_X, corridor.OBSTACLE_Y, corridor.OBSTACLE_RADIUS))

    gpu, gpu_env = whill_sim.gpu_offload_env(
        nvidia_loaded=os.path.exists('/proc/driver/nvidia/version'),
        display=os.environ.get('DISPLAY'),
        override=os.environ.get('WHILL_SIM_GPU'))
    drivers = base['drivers']
    rates = {entry['topic']: entry.get('rate_hz')
             for decl in drivers.values() for entry in (decl.get('publishes') or [])}
    model = whill_sim.robot_sdf(
        robot=robot, sim=sim_decl, gpu=gpu,
        lidar_rate_hz=float(rates[whill_sim.TOPIC_POINTS]),
        imu_rate_hz=float(rates[whill_sim.TOPIC_IMU]))

    def write(text: str, suffix: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            mode='w', suffix=suffix, prefix='whill-sim-', delete=False, encoding='utf-8')
        handle.write(text)
        handle.close()
        return handle.name

    world_path = write(world, '.world')
    model_path = write(model, '.sdf')
    gazebo_params = write(yaml.safe_dump(
        {'gazebo': {'ros__parameters': {'publish_rate': float(sim_decl['clock_hz'])}}}),
        '-gazebo.yaml')
    print(f'[whill_bringup] sim: world={world_path} model={model_path} '
          f'LiDAR={"GPU（NVIDIA）" if gpu else "CPU"}')

    actions = [SetEnvironmentVariable(name, value) for name, value in gpu_env.items()]
    # model:// を使っていないので、起動時にネットワークのモデル DB を見に行かせない
    # （繋がらないと数十秒待つ）。
    actions.append(SetEnvironmentVariable('GAZEBO_MODEL_DATABASE_URI', ''))
    actions.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('gazebo_ros'), 'launch', 'gzserver.launch.py')),
        # 画面（gzclient）は出さない。3D の表示は Foxglove に委譲する（設計原則 2）。
        launch_arguments={'world': world_path, 'verbose': 'false',
                          'params_file': gazebo_params}.items(),
    ))
    spawn = sim_decl['spawn']
    actions.append(Node(
        package='gazebo_ros', executable='spawn_entity.py', name='spawn_whill',
        output='screen',
        arguments=['-entity', 'whill', '-file', model_path,
                   '-x', str(spawn['x']), '-y', str(spawn['y']), '-z', '0.0',
                   '-Y', str(spawn['yaw'])]))

    # /scan は実機と同じ鎖で作る（点群 → pointcloud_to_laserscan）。設定も
    # 既存スタックのものをそのまま使う。実機はこの前に地面除去（Patchwork++）が
    # 挟まるが、sim の床は平らなので min_height 0.05 m で床は落ちる。
    p2ls = os.path.join(_require_existing_stack('whill_navigation'),
                        'config', 'pointcloud_to_laserscan.yaml')
    actions.append(Node(
        package='pointcloud_to_laserscan', executable='pointcloud_to_laserscan_node',
        name='pointcloud_to_laserscan', output='screen',
        parameters=[p2ls, {'use_sim_time': use_sim_time}],
        remappings=[('cloud_in', whill_sim.TOPIC_POINTS), ('scan', '/scan')]))
    return actions


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
        actions.extend(_sim_actions(robot, base, use_sim_time))

    # ---- TF ----------------------------------------------------------------
    # replay では出さない。bag に /tf_static が入っているので、こちらからも
    # 出すと二重になる（ADR-0004）。
    if mode != 'replay':
        actions.extend(_static_tf_nodes(robot, use_sim_time))

    if mode in ('mock', 'sim'):
        # mock / sim には localizer がいないので map -> odom を identity で固定する。
        # 実機ではこの TF は scan-to-map localizer が出す。両方が出すと
        # TF が二重になるため、mock / sim 限定であることを名前で明示する。
        # sim の odom は車輪の回転から積算するので、滑れば map とずれていく
        # （実機の odom と同じ性質。localizer が居ないので補正されない）。
        actions.append(Node(
            package='tf2_ros', executable='static_transform_publisher',
            name=f'{mode}_map_to_odom', output='log',
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
    map_yaml = (_corridor_map_yaml(required=(mode == 'sim'))
                if mode in ('mock', 'sim') else None)
    if map_yaml is not None:
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
    if mode in ('mock', 'sim'):
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

    # ---- 配車 --------------------------------------------------------------
    # **`dispatch_launch.py` は include しない。** あれは rosbridge (9090) と
    # 静的 UI の http.server (8000) も一緒に立てる composition で、
    # ROS への口が 2 つ増える（設計原則 1 違反）。要るのはノードだけ。
    if mode in ('mock', 'sim', 'real'):
        actions.append(Node(
            package='whill_dispatch', executable='dispatch_node',
            name='dispatch_node', output='screen',
            parameters=[{
                'waypoints_path': _waypoints_path(mode, robot),
                'use_sim_time': use_sim_time,
            }]))

    # ---- gateway -----------------------------------------------------------
    if start_gateway:
        actions.append(Node(
            package='whill_gateway', executable='gateway', name='whill_gateway',
            output='screen',
            # **gateway が終わったら launch ごと、失敗として止める**（K11, #49）。
            # `Shutdown()` だけだと終了コードが 0 になり、stackd が「停止」と
            # 表示して原因を隠す。理由は whill_bringup/gateway_guard.py。
            #
            # bag play 側には付けない。再生が終わっても gateway は残して
            # 「再生終了」を画面に出す（ADR-0004）。
            on_exit=on_gateway_exit,
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
