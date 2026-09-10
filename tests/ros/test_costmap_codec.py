"""costmap の符号化と部分更新のテスト。

`costmap_codec` は rclpy に依存しないので、ROS を立てずに全部検証できる。

見たいのは 2 点:
  1. RLE の往復が元の格子と一致する（欠けやずれを作らない）
  2. 部分更新を貼り込んだ結果が、全量を受け直したものと一致する
     — ADR-0002 の前提が実装で守られていること
"""

from __future__ import annotations

import pytest

from whill_gateway.costmap_codec import (
    apply_update,
    compression_ratio,
    costmap_frame,
    costmap_update_frame,
    decode_rle,
    encode_rle,
)


# ---- RLE の往復 ------------------------------------------------------------


def test_encode_folds_runs():
    assert encode_rle([0, 0, 0, 100, 100]) == [0, 3, 100, 2]


def test_encode_handles_unknown_cells():
    """未知 (-1) を 0 (空き) に潰さない。地図の穴が「通れる」に見えるのは危険。"""
    assert encode_rle([-1, -1, 0, 0]) == [-1, 2, 0, 2]


def test_encode_of_empty_is_empty():
    assert encode_rle([]) == []


def test_roundtrip_preserves_the_grid():
    cells = [0] * 10 + [100] * 5 + [-1] * 20 + [50, 60, 50]
    assert decode_rle(encode_rle(cells), len(cells)) == cells


def test_roundtrip_of_alternating_cells():
    """最悪ケース。壊れないことだけ確かめる（サイズは増える）。"""
    cells = [0, 100] * 50
    rle = encode_rle(cells)
    assert decode_rle(rle, len(cells)) == cells
    assert compression_ratio(rle, len(cells)) > 1.0


def test_bytes_input_restores_signed_values():
    """OccupancyGrid の data は int8。bytes で来ると -1 が 255 になる。"""
    assert encode_rle(bytes([255, 255, 0])) == [-1, 2, 0, 1]


def test_decode_rejects_odd_length():
    with pytest.raises(ValueError, match='偶数でない'):
        decode_rle([0, 2, 5], 5)


def test_decode_rejects_short_payload():
    """黙ってゼロ埋めしない。欠けが「空き」に見えるのは危険。"""
    with pytest.raises(ValueError, match='足りない'):
        decode_rle([0, 2], 5)


def test_decode_rejects_long_payload():
    with pytest.raises(ValueError, match='超えた'):
        decode_rle([0, 9], 5)


def test_decode_rejects_negative_count():
    with pytest.raises(ValueError, match='連続数が負'):
        decode_rle([0, -1], 5)


# ---- 圧縮率 ----------------------------------------------------------------


def test_compression_ratio_is_small_for_uniform_grid():
    cells = [0] * 40000
    assert compression_ratio(encode_rle(cells), len(cells)) < 0.001


def test_compression_ratio_of_empty_grid():
    assert compression_ratio([], 0) == 0.0


# ---- フレーム --------------------------------------------------------------


def test_costmap_frame_carries_geometry():
    frame = costmap_frame(scope='local', frame_id='map', resolution=0.05,
                          width=2, height=2, origin_x=-1.0, origin_y=-2.0,
                          cells=[0, 0, 0, 0], stamp=1.5, seq=3)
    assert frame['type'] == 'costmap'
    assert frame['scope'] == 'local'
    assert (frame['width'], frame['height']) == (2, 2)
    assert (frame['origin_x'], frame['origin_y']) == (-1.0, -2.0)
    assert frame['rle'] == [0, 4]
    assert frame['seq'] == 3


def test_costmap_frame_reports_ratio():
    """PNG へ切り替えるかの判断材料を運用中に見えるようにする（ADR-0002）。"""
    frame = costmap_frame(scope='local', frame_id='map', resolution=0.05,
                          width=100, height=100, origin_x=0.0, origin_y=0.0,
                          cells=[0] * 10000, stamp=0.0, seq=1)
    assert 0.0 < frame['ratio'] < 0.01


def test_update_frame_carries_the_rectangle():
    frame = costmap_update_frame(scope='local', x=3, y=4, width=2, height=1,
                                 cells=[100, 100], stamp=2.0, seq=7)
    assert frame['type'] == 'costmap_update'
    assert (frame['x'], frame['y'], frame['width'], frame['height']) == (3, 4, 2, 1)
    assert frame['rle'] == [100, 2]
    # クライアントが「どの全量に対する更新か」を判断できること
    assert frame['seq'] == 7


# ---- 部分更新の貼り込み ----------------------------------------------------


def test_apply_update_patches_the_rectangle():
    grid = [0] * 16  # 4x4
    out = apply_update(grid, 4, 4, x=1, y=1, width=2, height=2,
                       cells=[100, 100, 100, 100])
    assert out == [
        0, 0, 0, 0,
        0, 100, 100, 0,
        0, 100, 100, 0,
        0, 0, 0, 0,
    ]


def test_apply_update_does_not_mutate_the_input():
    grid = [0] * 16
    apply_update(grid, 4, 4, x=0, y=0, width=1, height=1, cells=[100])
    assert grid == [0] * 16


def test_patched_grid_matches_a_fresh_full_grid():
    """部分更新の積み重ねが、全量を受け直したものと一致すること。

    ADR-0002 の前提そのもの。ここが割れると、UI の地図が実際の costmap と
    静かにずれていく。
    """
    width = height = 8
    truth = [0] * (width * height)
    held = list(truth)

    # 3 回に分けて別々の矩形を書き換える
    patches = [
        (0, 0, 2, 2, [100] * 4),
        (5, 5, 3, 2, [50] * 6),
        (2, 4, 1, 4, [-1] * 4),
    ]
    for x, y, w, h, cells in patches:
        held = apply_update(held, width, height, x=x, y=y, width=w, height=h,
                            cells=cells)
        for row in range(h):
            start = (y + row) * width + x
            truth[start:start + w] = cells[row * w:(row + 1) * w]

    assert held == truth
    # RLE を経由しても同じであること
    assert decode_rle(encode_rle(held), len(held)) == truth


def test_apply_update_rejects_out_of_bounds():
    """黙って切り詰めない。ずれた地図で描画が続くと原因を追えない。"""
    grid = [0] * 16
    with pytest.raises(ValueError, match='はみ出している'):
        apply_update(grid, 4, 4, x=3, y=3, width=2, height=2, cells=[0] * 4)


def test_apply_update_rejects_negative_origin():
    grid = [0] * 16
    with pytest.raises(ValueError, match='はみ出している'):
        apply_update(grid, 4, 4, x=-1, y=0, width=2, height=1, cells=[0, 0])


def test_apply_update_rejects_wrong_cell_count():
    grid = [0] * 16
    with pytest.raises(ValueError, match='更新セル数'):
        apply_update(grid, 4, 4, x=0, y=0, width=2, height=2, cells=[0, 0])


def test_apply_update_rejects_mismatched_grid_length():
    with pytest.raises(ValueError, match='格子の長さ'):
        apply_update([0] * 10, 4, 4, x=0, y=0, width=1, height=1, cells=[0])
