"""sim（Gazebo Classic 11）の world と車体を組み立てる（K5）。

**rclpy にも Gazebo にも依存しない。** 設定の辞書から SDF の文字列を作るだけ
なので、Gazebo を立てずに検証できる。launch はこれを一時ファイルに書いて使う。

## なぜ生成するか（手で書いた SDF を置かない理由）

- **廊下は mock の地図と同じ寸法でなければならない。** ずれると「LiDAR は壁を
  見ているのに地図には無い」になり、Nav2 の挙動が mock と違う理由を切り分け
  られない。寸法の正は `scripts/make_mock_map.py` の定数
- **センサの取り付け位置は個体 yaml の `tf_static` が正。** SDF に同じ数字を
  書き写すと、TF と実際の光線の出どころが食い違う。#51 でまさに個体 yaml が
  実機とずれていたのを見つけたばかり
- トピック名は `cr2-base.yaml` の drivers 宣言が正

## 実機と同じ鎖にする

実機の `/scan` は LiDAR の生データではなく、**点群を `pointcloud_to_laserscan`
で高さ帯を切って作ったもの**（frame=base_link）。sim も点群だけを出し、
`/scan` は同じノード・同じ設定で作る（launch 側）。LaserScan を Gazebo から
直接出すと、傾けて付けた LiDAR（pitch +9 度）が床を障害物として拾う。
"""

from __future__ import annotations

import math
from typing import Any
from xml.sax.saxutils import escape

TOPIC_ODOM = '/whill/odom'
TOPIC_CMD_VEL = '/whill/controller/cmd_vel'
TOPIC_POINTS = '/velodyne_points'
TOPIC_IMU = '/imu/data_rep145'
"""トピック名は cr2-base.yaml の drivers 宣言と一致させる（テストが突き合わせる）。"""

WALL_HEIGHT = 2.0
"""壁の高さ。VLP-16 の上端（+15 度）が 20 m 先でも当たる高さは要らないが、
pointcloud_to_laserscan の max_height 1.6 m より高くしておく。"""

OBSTACLE_HEIGHT = 1.2


def _pose(xyz, rpy) -> str:
    return ' '.join(f'{v:.6f}' for v in (*xyz, *rpy))


def _box(name: str, size: tuple[float, float, float], pose: str) -> str:
    sx, sy, sz = size
    geometry = f'<geometry><box><size>{sx:.4f} {sy:.4f} {sz:.4f}</size></box></geometry>'
    return (f'<link name="{name}"><pose>{pose}</pose>'
            f'<collision name="c">{geometry}</collision>'
            f'<visual name="v">{geometry}</visual></link>')


def corridor_world_sdf(*, half_width: float, length: float, wall_thickness: float,
                       obstacle: tuple[float, float, float] | None,
                       name: str = 'whill_corridor') -> str:
    """mock の地図（make_mock_map.py）と同じ廊下。

    地図では壁を**廊下の内側から** wall_thickness ぶん占有にしている。壁の内面は
    x = ±(length/2 - t)、y = ±(half_width - t)。LiDAR が当たるのは内面なので、
    ここを地図と合わせる（外面を合わせると壁の厚みぶん地図とずれる）。
    """
    t = wall_thickness
    hx, hy = length / 2.0, half_width
    z = WALL_HEIGHT / 2.0
    walls = [
        # 左右（y 方向）の長い壁。中心は内面から t/2 外側
        _box('wall_north', (length, t, WALL_HEIGHT), _pose((0.0, hy - t / 2, z), (0, 0, 0))),
        _box('wall_south', (length, t, WALL_HEIGHT), _pose((0.0, -(hy - t / 2), z), (0, 0, 0))),
        # 前後（x 方向）の短い壁
        _box('wall_east', (t, 2 * half_width, WALL_HEIGHT), _pose((hx - t / 2, 0.0, z), (0, 0, 0))),
        _box('wall_west', (t, 2 * half_width, WALL_HEIGHT), _pose((-(hx - t / 2), 0.0, z), (0, 0, 0))),
    ]
    obstacle_sdf = ''
    if obstacle is not None:
        ox, oy, radius = obstacle
        geometry = (f'<geometry><cylinder><radius>{radius:.4f}</radius>'
                    f'<length>{OBSTACLE_HEIGHT:.4f}</length></cylinder></geometry>')
        obstacle_sdf = (
            f'<model name="obstacle"><static>true</static>'
            f'<pose>{_pose((ox, oy, OBSTACLE_HEIGHT / 2), (0, 0, 0))}</pose>'
            f'<link name="l"><collision name="c">{geometry}</collision>'
            f'<visual name="v">{geometry}</visual></link></model>')

    # 地面は model:// を使わずに直接書く。Gazebo Classic は model:// を解決する
    # ために起動時にネットワークのモデルデータベースを見に行き、繋がらないと
    # 数十秒待つ。
    ground = ('<model name="ground"><static>true</static><link name="l">'
              '<collision name="c"><geometry><plane><normal>0 0 1</normal>'
              '<size>100 100</size></plane></geometry></collision>'
              '<visual name="v"><geometry><plane><normal>0 0 1</normal>'
              '<size>100 100</size></plane></geometry></visual></link></model>')
    return (
        '<?xml version="1.0"?>\n'
        f'<sdf version="1.6"><world name="{escape(name)}">'
        '<gravity>0 0 -9.81</gravity>'
        # 実時間で回す（設計原則 7: 非リアルタイム高速 sim は作らない）
        '<physics type="ode"><real_time_factor>1.0</real_time_factor>'
        '<max_step_size>0.001</max_step_size><real_time_update_rate>1000</real_time_update_rate></physics>'
        '<light name="sun" type="directional"><pose>0 0 10 0 0 0</pose>'
        '<direction>-0.3 0.2 -1</direction></light>'
        f'{ground}'
        f'<model name="corridor"><static>true</static>{"".join(walls)}</model>'
        f'{obstacle_sdf}'
        '</world></sdf>\n')


def _inertia_box(mass: float, x: float, y: float, z: float) -> str:
    ixx = mass * (y * y + z * z) / 12.0
    iyy = mass * (x * x + z * z) / 12.0
    izz = mass * (x * x + y * y) / 12.0
    return (f'<inertial><mass>{mass:.4f}</mass><inertia><ixx>{ixx:.6f}</ixx><iyy>{iyy:.6f}</iyy>'
            f'<izz>{izz:.6f}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>')


def _inertia_cylinder(mass: float, radius: float, length: float) -> str:
    ixx = mass * (3 * radius * radius + length * length) / 12.0
    izz = mass * radius * radius / 2.0
    return (f'<inertial><mass>{mass:.4f}</mass><inertia><ixx>{ixx:.6f}</ixx><iyy>{ixx:.6f}</iyy>'
            f'<izz>{izz:.6f}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>')


def lidar_samples(sim: dict[str, Any]) -> tuple[int, int]:
    """(水平, 垂直) のサンプル数。VLP-16 相当で 900 x 16。"""
    lidar = sim['lidar']
    horizontal = int(round(360.0 / float(lidar['horizontal_resolution_deg'])))
    return horizontal, int(lidar['rings'])


def robot_sdf(*, robot: dict[str, Any], sim: dict[str, Any], lidar_rate_hz: float,
              imu_rate_hz: float, gpu: bool, name: str = 'whill') -> str:
    """差動二輪の箱と、個体 yaml の位置に付けた LiDAR / IMU。

    **TF は出さない。** odom -> base_link は既存スタックの EKF、センサの static TF
    は個体 yaml から launch が出す（mock と同じ配線）。プラグインが TF を出すと
    二重になり、「sim では動くが実機で落ちる」を作り込む。

    `gpu` が False なら LiDAR を CPU の ray にする。GPU 版はディスプレイ（GL の
    文脈）が要るので、ヘッドレスでは使えない。
    """
    body, wheel = sim['body'], sim['drive_wheel']
    tf = robot['tf_static']
    radius = float(wheel['radius'])
    separation = float(wheel['separation'])
    width = float(wheel['width'])

    # base_link は床の高さ（既存スタックの pointcloud_to_laserscan の前提）。
    # 車輪の中心は半径ぶん上。箱は車輪の上に載せる。
    body_z = radius + float(body['height']) / 2.0
    chassis = (
        f'<link name="base_link">{_inertia_box(float(body["mass"]), float(body["length"]), float(body["width"]), float(body["height"]))}'
        f'<collision name="c"><pose>{_pose((0, 0, body_z), (0, 0, 0))}</pose>'
        f'<geometry><box><size>{body["length"]} {body["width"]} {body["height"]}</size></box></geometry></collision>'
        f'<visual name="v"><pose>{_pose((0, 0, body_z), (0, 0, 0))}</pose>'
        f'<geometry><box><size>{body["length"]} {body["width"]} {body["height"]}</size></box></geometry></visual>'
        f'{_sensors(tf, sim, lidar_rate_hz, imu_rate_hz, gpu)}'
        # 前後の自在輪の代わりに、摩擦ゼロの球を 2 つ置く
        + ''.join(
            f'<collision name="caster_{tag}"><pose>{_pose((x, 0, radius / 2), (0, 0, 0))}</pose>'
            f'<geometry><sphere><radius>{radius / 2:.4f}</radius></sphere></geometry>'
            '<surface><friction><ode><mu>0</mu><mu2>0</mu2></ode></friction></surface></collision>'
            for tag, x in (('front', float(body['length']) / 2 - radius),
                           ('rear', -(float(body['length']) / 2 - radius))))
        + '</link>')

    wheels = ''
    for side, sign in (('left', 1.0), ('right', -1.0)):
        wheels += (
            f'<link name="{side}_wheel"><pose>{_pose((0, sign * separation / 2, radius), (-math.pi / 2, 0, 0))}</pose>'
            f'{_inertia_cylinder(5.0, radius, width)}'
            f'<collision name="c"><geometry><cylinder><radius>{radius}</radius><length>{width}</length></cylinder></geometry>'
            '<surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision>'
            f'<visual name="v"><geometry><cylinder><radius>{radius}</radius><length>{width}</length></cylinder></geometry></visual>'
            '</link>'
            f'<joint name="{side}_wheel_joint" type="revolute"><parent>base_link</parent><child>{side}_wheel</child>'
            '<axis><xyz>0 0 1</xyz></axis></joint>')

    drive = (
        '<plugin name="whill_drive" filename="libgazebo_ros_diff_drive.so">'
        '<ros>'
        f'<remapping>cmd_vel:={TOPIC_CMD_VEL}</remapping>'
        f'<remapping>odom:={TOPIC_ODOM}</remapping>'
        '</ros>'
        f'<update_rate>{float(sim["drive_update_hz"])}</update_rate>'
        '<left_joint>left_wheel_joint</left_joint><right_joint>right_wheel_joint</right_joint>'
        f'<wheel_separation>{separation}</wheel_separation>'
        f'<wheel_diameter>{2 * radius}</wheel_diameter>'
        '<max_wheel_torque>50</max_wheel_torque><max_wheel_acceleration>2.0</max_wheel_acceleration>'
        '<publish_odom>true</publish_odom>'
        # TF は出さない（odom -> base_link は EKF の役目。docstring 参照）
        '<publish_odom_tf>false</publish_odom_tf><publish_wheel_tf>false</publish_wheel_tf>'
        '<odometry_frame>odom</odometry_frame><robot_base_frame>base_link</robot_base_frame>'
        # 0 = 車輪の回転から積算（実機のエンコーダと同じ性質。滑れば誤差が出る）
        '<odometry_source>0</odometry_source>'
        '</plugin>')

    return ('<?xml version="1.0"?>\n'
            f'<sdf version="1.6"><model name="{escape(name)}">'
            f'{chassis}{wheels}{drive}</model></sdf>\n')


def _sensors(tf: dict[str, Any], sim: dict[str, Any], lidar_rate_hz: float,
             imu_rate_hz: float, gpu: bool) -> str:
    """base_link に直付けしたセンサ。位置は個体 yaml の tf_static（base_link 基準）。

    親が base_link でないフレームは扱わない（いまの個体 yaml はすべて base_link
    直下。#51 / tf_static の突き合わせテストが固定している）。
    """
    for frame in ('velodyne', 'imu_link'):
        if tf[frame]['parent'] != 'base_link':
            raise ValueError(f'{frame} の親が base_link でない: {tf[frame]["parent"]}')

    lidar = sim['lidar']
    horizontal, vertical = lidar_samples(sim)
    sensor_type = 'gpu_ray' if gpu else 'ray'
    velodyne = tf['velodyne']
    lidar_sdf = (
        f'<sensor name="velodyne" type="{sensor_type}">'
        f'<pose>{_pose(velodyne["xyz"], velodyne["rpy"])}</pose>'
        f'<always_on>true</always_on><update_rate>{lidar_rate_hz}</update_rate>'
        '<ray><scan>'
        f'<horizontal><samples>{horizontal}</samples><resolution>1</resolution>'
        f'<min_angle>{-math.pi:.6f}</min_angle><max_angle>{math.pi - math.radians(float(lidar["horizontal_resolution_deg"])):.6f}</max_angle></horizontal>'
        f'<vertical><samples>{vertical}</samples><resolution>1</resolution>'
        f'<min_angle>{math.radians(float(lidar["min_elevation_deg"])):.6f}</min_angle>'
        f'<max_angle>{math.radians(float(lidar["max_elevation_deg"])):.6f}</max_angle></vertical>'
        '</scan>'
        f'<range><min>{lidar["range_min"]}</min><max>{lidar["range_max"]}</max><resolution>0.01</resolution></range>'
        f'<noise><type>gaussian</type><mean>0</mean><stddev>{lidar["noise_stddev"]}</stddev></noise>'
        '</ray>'
        '<plugin name="velodyne_driver" filename="libgazebo_ros_ray_sensor.so">'
        f'<ros><remapping>~/out:={TOPIC_POINTS}</remapping></ros>'
        '<output_type>sensor_msgs/PointCloud2</output_type>'
        '<frame_name>velodyne</frame_name>'
        '</plugin></sensor>')

    imu = tf['imu_link']
    noise = float(sim['imu']['noise_stddev'])
    axis_noise = ''.join(
        f'<{axis}><noise type="gaussian"><mean>0</mean><stddev>{noise}</stddev></noise></{axis}>'
        for axis in ('x', 'y', 'z'))
    imu_sdf = (
        '<sensor name="imu" type="imu">'
        f'<pose>{_pose(imu["xyz"], imu["rpy"])}</pose>'
        f'<always_on>true</always_on><update_rate>{imu_rate_hz}</update_rate>'
        f'<imu><angular_velocity>{axis_noise}</angular_velocity>'
        f'<linear_acceleration>{axis_noise}</linear_acceleration></imu>'
        '<plugin name="rt_9axis_driver" filename="libgazebo_ros_imu_sensor.so">'
        f'<ros><remapping>~/out:={TOPIC_IMU}</remapping></ros>'
        '<frame_name>imu_link</frame_name>'
        # 実機の RT-USB-9AXIS-00 は姿勢を推定しない（ADR-0006）。EKF も orientation
        # を使わないので、ここで何を入れても走りは変わらない。
        '<initial_orientation_as_reference>false</initial_orientation_as_reference>'
        '</plugin></sensor>')
    return lidar_sdf + imu_sdf


def gpu_offload_env(*, nvidia_loaded: bool, display: str | None,
                    override: str | None) -> tuple[bool, dict[str, str]]:
    """Gazebo を NVIDIA で描画するか、と、そのための環境変数。

    この PC は Intel 内蔵 + NVIDIA のハイブリッドで `prime-select` が on-demand。
    **何も指定しないと Gazebo は Intel 側で描画する**（2026-09-16 実測）。
    PRIME のオフロード指定を付けると NVIDIA を使う。

    - ディスプレイが無ければ GPU を使わない（GPU 版 LiDAR は GL の文脈が要る）
    - NVIDIA のモジュールが載っていなければ付けない（付けると GL ごと壊れる）
    - `WHILL_SIM_GPU=off` で明示的に切れる（切り分け用）
    """
    if (override or '').lower() == 'off':
        return False, {}
    if not display or not nvidia_loaded:
        return False, {}
    return True, {'__NV_PRIME_RENDER_OFFLOAD': '1', '__GLX_VENDOR_LIBRARY_NAME': 'nvidia'}
