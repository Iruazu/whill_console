"""`whill tap` の 1 行要約（#51 の tf）。"""

from __future__ import annotations

from whill_cli.tap import summarize


def test_tf_names_only_stopped_and_missing_edges():
    """健全な辺は数だけ。止まった辺と来ていない辺は名前で出す（端末で切り分けるため）。"""
    line = summarize({
        'type': 'tf',
        'parents': {'odom': 'map', 'base_link': 'odom'},
        'edges': [
            {'parent': 'map', 'child': 'odom', 'level': 'crit', 'age': 4.36},
            {'parent': 'odom', 'child': 'base_link', 'level': 'ok', 'age': 0.03},
        ],
        'missing': [{'parent': 'base_link', 'child': 'imu_link'}],
    })
    assert '2 フレーム' in line
    assert 'map->odom:crit(4.36s)' in line
    assert 'odom->base_link' not in line
    assert 'base_link->imu_link' in line


def test_tf_from_an_older_gateway_still_summarizes():
    assert summarize({'type': 'tf', 'parents': {'odom': 'map'}}) == 'tf       1 フレーム'
