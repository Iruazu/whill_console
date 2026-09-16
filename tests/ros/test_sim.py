"""mode=sim の world と車体（K5）。

`whill_bringup/sim.py` は rclpy にも Gazebo にも依存しない。設定から SDF を
組むだけなので、Gazebo を立てずに検証できる。

見たいのは「sim が mock・実機と**同じ契約**で動くこと」:

  1. 廊下の壁の内面が mock の地図と一致する（ずれると LiDAR と地図が食い違う）
  2. トピック名が cr2-base.yaml の drivers 宣言と一致する
  3. センサの位置が個体 yaml の tf_static と一致する（TF と光線の出どころ）
  4. プラグインが TF を出さない（odom -> base_link は EKF、static は launch）
"""

from __future__ import annotations

import ast
import importlib.util
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ros' / 'src' / 'whill_bringup'))

from whill_bringup import sim  # noqa: E402

BASE = yaml.safe_load((ROOT / 'config' / 'robots' / 'cr2-base.yaml').read_text('utf-8'))
ROBOT = yaml.safe_load((ROOT / 'config' / 'robots' / 'cr2-01.yaml').read_text('utf-8'))


def _corridor():
    spec = importlib.util.spec_from_file_location(
        'make_mock_map', ROOT / 'scripts' / 'make_mock_map.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _world(obstacle=True) -> ET.Element:
    c = _corridor()
    text = sim.corridor_world_sdf(
        half_width=c.HALF_WIDTH, length=c.LENGTH, wall_thickness=c.WALL_THICKNESS,
        obstacle=(c.OBSTACLE_X, c.OBSTACLE_Y, c.OBSTACLE_RADIUS) if obstacle else None)
    return ET.fromstring(text.split('\n', 1)[1])


def _robot(gpu=True) -> ET.Element:
    text = sim.robot_sdf(robot=ROBOT, sim=BASE['sim'], gpu=gpu,
                         lidar_rate_hz=10.0, imu_rate_hz=100.0)
    return ET.fromstring(text.split('\n', 1)[1])


def _floats(text: str) -> list[float]:
    return [float(v) for v in text.split()]


# ---- 廊下 -------------------------------------------------------------------


def test_wall_inner_faces_match_the_mock_map():
    """LiDAR が当たるのは内面。地図の free_bounds() と一致すること。"""
    c = _corridor()
    x_min, x_max, y_min, y_max = c.free_bounds()
    world = _world()
    faces = {}
    for link in world.iter('link'):
        name = link.get('name')
        if not name.startswith('wall_'):
            continue
        x, y, _, *_ = _floats(link.find('pose').text)
        sx, sy, _ = _floats(link.find('collision/geometry/box/size').text)
        faces[name] = {'wall_north': y - sy / 2, 'wall_south': y + sy / 2,
                       'wall_east': x - sx / 2, 'wall_west': x + sx / 2}[name]
    assert faces['wall_north'] == pytest.approx(y_max)
    assert faces['wall_south'] == pytest.approx(y_min)
    assert faces['wall_east'] == pytest.approx(x_max)
    assert faces['wall_west'] == pytest.approx(x_min)


def test_obstacle_is_where_the_mock_puts_it():
    """地図に描かない障害物。mock_velodyne の既定と同じ場所にあること。"""
    c = _corridor()
    model = next(m for m in _world().iter('model') if m.get('name') == 'obstacle')
    x, y, *_ = _floats(model.find('pose').text)
    radius = float(model.find('link/collision/geometry/cylinder/radius').text)
    assert (x, y, radius) == pytest.approx((c.OBSTACLE_X, c.OBSTACLE_Y, c.OBSTACLE_RADIUS))


def test_mock_velodyne_defaults_agree_with_the_map_constants():
    """mock の合成 LiDAR と sim の world が、同じ位置に障害物を置いていること。"""
    c = _corridor()
    source = (ROOT / 'ros' / 'src' / 'whill_mock_drivers' / 'whill_mock_drivers' /
              'mock_velodyne.py').read_text('utf-8')
    defaults = {}
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'declare_parameter' and len(node.args) == 2):
            defaults[ast.literal_eval(node.args[0])] = ast.literal_eval(node.args[1])
    assert defaults['corridor_half_width'] == c.HALF_WIDTH
    assert defaults['corridor_length'] == c.LENGTH
    assert (defaults['obstacle_x'], defaults['obstacle_y'], defaults['obstacle_radius']) == \
        (c.OBSTACLE_X, c.OBSTACLE_Y, c.OBSTACLE_RADIUS)


def test_world_does_not_fetch_models_from_the_network():
    """model:// を使うと、Gazebo Classic は起動時にネットワークの DB を見に行って待つ。"""
    c = _corridor()
    text = sim.corridor_world_sdf(half_width=c.HALF_WIDTH, length=c.LENGTH,
                                  wall_thickness=c.WALL_THICKNESS, obstacle=None)
    assert 'model://' not in text


def test_world_runs_in_real_time():
    """設計原則 7: 非リアルタイム高速 sim は作らない。"""
    assert float(_world().find('.//physics/real_time_factor').text) == 1.0


# ---- 車体 -------------------------------------------------------------------


def _declared_publish_topics() -> set[str]:
    return {entry['topic'] for decl in BASE['drivers'].values()
            for entry in decl.get('publishes') or []}


def test_topics_match_the_driver_declarations():
    """トピック名は cr2-base.yaml が正。sim が別名で出すと上位が繋がらない。"""
    published = _declared_publish_topics()
    assert sim.TOPIC_ODOM in published
    assert sim.TOPIC_POINTS in published
    assert sim.TOPIC_IMU in published
    subscribes = {entry['topic'] for entry in BASE['drivers']['whill_serial']['subscribes']}
    assert sim.TOPIC_CMD_VEL in subscribes

    text = sim.robot_sdf(robot=ROBOT, sim=BASE['sim'], gpu=True,
                         lidar_rate_hz=10.0, imu_rate_hz=100.0)
    for topic in (sim.TOPIC_ODOM, sim.TOPIC_CMD_VEL, sim.TOPIC_POINTS, sim.TOPIC_IMU):
        assert topic in text


def test_drive_plugin_publishes_no_tf():
    """odom -> base_link は EKF が唯一の publisher（mock と同じ配線）。"""
    plugin = next(p for p in _robot().iter('plugin')
                  if p.get('filename') == 'libgazebo_ros_diff_drive.so')
    assert plugin.find('publish_odom_tf').text == 'false'
    assert plugin.find('publish_wheel_tf').text == 'false'


@pytest.mark.parametrize('sensor_name, frame', [('velodyne', 'velodyne'), ('imu', 'imu_link')])
def test_sensor_poses_come_from_the_robot_yaml(sensor_name, frame):
    """センサ位置の単一ソースは個体 yaml。SDF に別の数字を書かない。"""
    sensor = next(s for s in _robot().iter('sensor') if s.get('name') == sensor_name)
    pose = _floats(sensor.find('pose').text)
    entry = ROBOT['tf_static'][frame]
    assert pose == pytest.approx(list(entry['xyz']) + list(entry['rpy']), abs=1e-6)


def test_lidar_is_a_vlp16_like_point_cloud():
    """実機と同じく点群を出す。/scan は launch の pointcloud_to_laserscan が作る。"""
    sensor = next(s for s in _robot().iter('sensor') if s.get('name') == 'velodyne')
    assert int(sensor.find('ray/scan/vertical/samples').text) == 16
    assert int(sensor.find('ray/scan/horizontal/samples').text) == 900
    output = sensor.find('plugin/output_type').text
    assert output == 'sensor_msgs/PointCloud2'
    # 点数の目安が drivers テレメトリの警告（12000 点未満）を下回らないこと
    horizontal, vertical = sim.lidar_samples(BASE['sim'])
    assert horizontal * vertical > 12000


@pytest.mark.parametrize('gpu, sensor_type', [(True, 'gpu_ray'), (False, 'ray')])
def test_gpu_flag_switches_the_lidar(gpu, sensor_type):
    sensor = next(s for s in _robot(gpu).iter('sensor') if s.get('name') == 'velodyne')
    assert sensor.get('type') == sensor_type


def test_non_base_link_sensor_parent_is_rejected():
    """親が base_link でないと、SDF に直付けした位置が TF と食い違う。"""
    robot = yaml.safe_load(yaml.safe_dump(ROBOT))
    robot['tf_static']['velodyne']['parent'] = 'imu_link'
    with pytest.raises(ValueError, match='base_link'):
        sim.robot_sdf(robot=robot, sim=BASE['sim'], gpu=True,
                      lidar_rate_hz=10.0, imu_rate_hz=100.0)


def test_wheels_touch_the_ground_and_base_link_is_at_floor_level():
    """base_link は床の高さ（既存スタックの pointcloud_to_laserscan の前提）。"""
    radius = BASE['sim']['drive_wheel']['radius']
    for link in _robot().iter('link'):
        if link.get('name', '').endswith('_wheel'):
            assert _floats(link.find('pose').text)[2] == pytest.approx(radius)


def test_body_fits_in_the_nav2_robot_radius():
    """Nav2 の robot_radius より大きい箱にすると、通れるはずの所で当たる。"""
    body = BASE['sim']['body']
    assert math.hypot(body['length'] / 2, body['width'] / 2) <= 0.6


# ---- GPU --------------------------------------------------------------------


def test_gpu_offload_is_used_when_nvidia_and_a_display_are_present():
    """on-demand のハイブリッド構成では、指定しないと Intel 側で描画する（2026-09-16 実測）。"""
    gpu, env = sim.gpu_offload_env(nvidia_loaded=True, display=':1', override=None)
    assert gpu is True
    assert env == {'__NV_PRIME_RENDER_OFFLOAD': '1', '__GLX_VENDOR_LIBRARY_NAME': 'nvidia'}


@pytest.mark.parametrize('nvidia, display, override', [
    (False, ':1', None),     # NVIDIA が無いのに付けると GL ごと壊れる
    (True, None, None),      # ヘッドレス。GPU 版 LiDAR は GL の文脈が要る
    (True, ':1', 'off'),     # 切り分け用に明示的に切る
])
def test_gpu_offload_is_not_used_otherwise(nvidia, display, override):
    gpu, env = sim.gpu_offload_env(nvidia_loaded=nvidia, display=display, override=override)
    assert gpu is False
    assert env == {}


# ---- launch の配線 ----------------------------------------------------------


LAUNCH = (ROOT / 'ros' / 'src' / 'whill_bringup' / 'launch' / 'bringup_launch.py').read_text('utf-8')


def test_sim_is_wired_not_rejected():
    assert "mode=sim はまだ配線していない" not in LAUNCH
    assert '_sim_actions(robot, base, use_sim_time)' in LAUNCH


def test_scan_is_made_the_same_way_as_on_the_robot():
    """/scan は既存スタックの pointcloud_to_laserscan.yaml をそのまま使う。"""
    assert "'pointcloud_to_laserscan.yaml'" in LAUNCH
    assert "_require_existing_stack('whill_navigation')" in LAUNCH


def test_sim_reuses_the_mock_wiring():
    """twist_mux / EKF / map -> odom / 配車地点は mock と同じもの。"""
    assert LAUNCH.count("if mode in ('mock', 'sim'):") >= 2
    assert "if mode in ('mock', 'sim', 'real'):" in LAUNCH
