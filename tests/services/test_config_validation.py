"""config/ の検証テスト。

ここが赤いまま他のことをしないこと。設定の単一ソースが壊れていると、
mock も実機も同じ設定で走っている保証が消える。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from whill_cli import config as cli_config
from whill_cli.validate import validate_all

CONFIG_ROOT = Path(__file__).resolve().parents[2] / 'config'


def test_repo_config_is_valid():
    assert validate_all(CONFIG_ROOT) == []


def test_every_param_has_a_real_reason():
    """description が「単位だけ」「型だけ」で終わっていないこと。

    UI のツールチップにそのまま出るので、値の由来が書かれていないと
    走行中に触っていいかどうかが判断できない。
    """
    params = yaml.safe_load((CONFIG_ROOT / 'params.yaml').read_text())['params']
    too_short = [f'{p["node"]}.{p["name"]}' for p in params
                 if len(p['description'].strip()) < 15]
    assert too_short == [], f'説明が短すぎる: {too_short}'


def test_locked_params_cover_speed_and_accel():
    """速度・加速度の上限は走行中に変えられないこと。

    走行中にこれらが変わると乗っている人に直接効く。safety_class の
    付け忘れをテストで止める。
    """
    params = yaml.safe_load((CONFIG_ROOT / 'params.yaml').read_text())['params']
    by_key = {f'{p["node"]}.{p["name"]}': p for p in params}
    must_lock = [
        'controller_server.FollowPath.desired_linear_vel',
        'velocity_smoother.max_velocity',
        'velocity_smoother.max_accel',
    ]
    for key in must_lock:
        assert key in by_key, f'{key} が params.yaml に無い'
        assert by_key[key]['safety_class'] == 'locked_while_moving', \
            f'{key} は locked_while_moving であるべき'


def test_costmap_inflation_is_not_below_robot_radius():
    """inflation_radius < robot_radius を既定値で作らないこと。

    07-21 の実走で、この関係が崩れて経路が走行可能域の端を這った。
    数値を触るときに同じ穴に落ちないようテストで固定する。
    """
    params = yaml.safe_load((CONFIG_ROOT / 'params.yaml').read_text())['params']
    by_key = {f'{p["node"]}.{p["name"]}': p['default'] for p in params}
    for scope in ('local_costmap', 'global_costmap'):
        radius = by_key[f'{scope}.robot_radius']
        inflation = by_key[f'{scope}.inflation_layer.inflation_radius']
        assert inflation >= radius, \
            f'{scope}: inflation_radius {inflation} < robot_radius {radius}'


def test_transform_tolerance_is_consistent():
    """bt_navigator / controller_server / behavior_server で同値であること。"""
    params = yaml.safe_load((CONFIG_ROOT / 'params.yaml').read_text())['params']
    values = {p['node']: p['default'] for p in params
              if p['name'].endswith('transform_tolerance')}
    assert len(set(values.values())) == 1, f'食い違っている: {values}'


def test_declared_topics_for_mock_mode():
    topics = cli_config.declared_topics('cr2-01', 'mock')
    assert '/whill/odom' in topics
    assert '/velodyne_points' in topics
    assert '/scan' in topics
    # realsense は既定で起動しないので mock の宣言に入らない
    assert not any(t.startswith('/camera/') for t in topics)


def test_declared_topics_for_sim_mode():
    """sim はドライバのノードが無いが、Gazebo が同じトピックを出す（K5）。

    宣言が無いと whill doctor が中身の無い合格を出す。
    """
    topics = cli_config.declared_topics('cr2-01', 'sim')
    assert {'/whill/odom', '/velodyne_points', '/scan', '/imu/data_rep145', '/clock'} <= set(topics)
    # sim に無いものを要求しない
    assert '/whill/states/model_cr2' not in topics


def test_camera_opt_in_adds_camera_topics():
    topics = cli_config.declared_topics('cr2-01', 'mock', include_camera=True)
    assert any(t.startswith('/camera/') for t in topics)


def test_all_robots_are_loadable():
    for robot_id in cli_config.known_robots():
        data = cli_config.robot_config(robot_id)
        assert data['robot_id'] == robot_id


def test_only_cr2_01_claims_measured_tf():
    """未納の個体が「採寸済み」を名乗らないこと。

    推定値を採寸値の顔で置くのが一番危ない。cr2-02/03 は実車が来るまで
    measured: false であること。
    """
    for robot_id in cli_config.known_robots():
        if robot_id == 'cr2-01':
            continue
        tf = cli_config.robot_config(robot_id).get('tf_static') or {}
        measured = [name for name, entry in tf.items() if entry.get('measured')]
        assert measured == [], f'{robot_id} が未採寸なのに measured: true: {measured}'


# ---- スキーマが実際にエラーを捕まえることの確認 ----


def _write_config(tmp_path: Path, mutate) -> Path:
    """config/ を tmp にコピーし、mutate で壊してからパスを返す。"""
    root = tmp_path / 'config'
    (root / 'robots').mkdir(parents=True)
    (root / 'presets').mkdir(parents=True)
    for src in CONFIG_ROOT.rglob('*.yaml'):
        dest = root / src.relative_to(CONFIG_ROOT)
        dest.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
    mutate(root)
    return root


def test_unknown_preset_key_is_rejected(tmp_path):
    def mutate(root: Path):
        data = yaml.safe_load((root / 'presets' / 'cautious.yaml').read_text())
        data['overrides']['controller_server.FollowPath.no_such_param'] = 1.0
        (root / 'presets' / 'cautious.yaml').write_text(yaml.safe_dump(data))

    errors = validate_all(_write_config(tmp_path, mutate))
    assert any('no_such_param' in e for e in errors)


def test_duplicate_topic_declaration_is_rejected(tmp_path):
    def mutate(root: Path):
        path = root / 'robots' / 'cr2-base.yaml'
        data = yaml.safe_load(path.read_text())
        # rt_9axis が velodyne と同じトピックを出す宣言にする
        data['drivers']['rt_9axis']['publishes'].append(
            copy.deepcopy(data['drivers']['velodyne']['publishes'][0]))
        path.write_text(yaml.safe_dump(data, allow_unicode=True))

    errors = validate_all(_write_config(tmp_path, mutate))
    assert any('二重に publish 宣言' in e for e in errors)


@pytest.mark.parametrize('edit, message', [
    (lambda edges: edges[0].update(warn_sec=5.0), 'warn_sec < crit_sec'),
    (lambda edges: edges.append(dict(edges[0])), '二重に宣言'),
])
def test_bad_tf_expectation_is_rejected(tmp_path, edit, message):
    """tf パネルの閾値（#51）。逆転や二重宣言は黙って通さない。"""
    def mutate(root: Path):
        path = root / 'robots' / 'cr2-base.yaml'
        data = yaml.safe_load(path.read_text())
        edit(data['tf']['dynamic'])
        path.write_text(yaml.safe_dump(data, allow_unicode=True))

    errors = validate_all(_write_config(tmp_path, mutate))
    assert any(message in e for e in errors), errors


def test_mode_referring_to_unknown_driver_is_rejected(tmp_path):
    def mutate(root: Path):
        path = root / 'robots' / 'cr2-base.yaml'
        data = yaml.safe_load(path.read_text())
        data['modes']['mock']['drivers'].append('lidar_that_does_not_exist')
        path.write_text(yaml.safe_dump(data, allow_unicode=True))

    errors = validate_all(_write_config(tmp_path, mutate))
    assert any('lidar_that_does_not_exist' in e for e in errors)


def test_double_array_without_elements_is_rejected(tmp_path):
    def mutate(root: Path):
        path = root / 'params.yaml'
        data = yaml.safe_load(path.read_text())
        for entry in data['params']:
            if entry['type'] == 'double_array':
                entry.pop('elements')
                break
        path.write_text(yaml.safe_dump(data, allow_unicode=True))

    errors = validate_all(_write_config(tmp_path, mutate))
    assert any('elements' in e for e in errors)


@pytest.mark.parametrize('robot_id', ['cr2-01', 'cr2-02', 'cr2-03'])
def test_domain_ids_are_distinct(robot_id):
    ids = {r: cli_config.robot_config(r)['ros_domain_id']
           for r in cli_config.known_robots()}
    assert len(set(ids.values())) == len(ids), f'domain_id が重複している: {ids}'
    assert robot_id in ids


def test_imu_driver_is_the_rt_9axis():
    """実装計画書の `bno085` は記載ミス。現車は RT-USB-9AXIS-00。

    宣言名が実機と食い違うと、real モードを配線する人が別のドライバを
    探しに行く。ここで固定しておく（Q1、2026-09-10 ユーザー確認済み）。
    """
    drivers = cli_config.base_config()['drivers']
    assert 'rt_9axis' in drivers
    assert 'bno085' not in drivers
    assert drivers['rt_9axis']['real_package'] == 'rt_usb_9axisimu_driver'


def test_lifecycle_drivers_are_declared():
    """LifecycleNode のドライバは `lifecycle: true` を宣言していること。

    RT 9軸は configure → activate の間に約 1.5 s の待ちが要る。宣言が無いと
    real モードの launch が通常ノードとして起動し、activate が失敗する。
    """
    drivers = cli_config.base_config()['drivers']
    assert drivers['rt_9axis'].get('lifecycle') is True
