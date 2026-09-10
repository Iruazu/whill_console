#!/usr/bin/env python3
"""mock モード用の占有格子を生成する。

mock_velodyne が合成する廊下と同じ寸法の地図を作る。ここがずれると
「LiDAR は壁を見ているのに地図には無い」状態になり、Nav2 の挙動が
実機と違う理由の切り分けができなくなる。寸法を変えるときは
mock_velodyne のパラメータ（corridor_half_width / corridor_length）と
必ず一対で変えること。

冪等。再実行すると同じ内容で上書きする。
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / 'ros' / 'src' / 'whill_bringup' / 'config'

# 廊下の寸法。**mock_velodyne のパラメータと一対**（module docstring 参照）。
#
# 定数として出しているのは、生成物（mock_corridor.yaml）が gitignore されて
# いて CI には無いため。配車地点が廊下の中にあるかを確かめるテストは、
# 生成物ではなくここを見る。
HALF_WIDTH = 2.5
LENGTH = 20.0
RESOLUTION = 0.05
WALL_THICKNESS = 0.15
MARGIN = 1.0


def free_bounds(half_width: float = HALF_WIDTH, length: float = LENGTH,
                wall_thickness: float = WALL_THICKNESS,
                ) -> tuple[float, float, float, float]:
    """走行可能な内側の矩形 (x_min, x_max, y_min, y_max)。

    廊下は原点中心。壁の内側だけを返すので、ここに入っていない座標を
    目標にすると Nav2 は経路を引けない。
    """
    x = length / 2.0 - wall_thickness
    y = half_width - wall_thickness
    return -x, x, -y, y


def build(half_width: float, length: float, resolution: float,
          wall_thickness: float, margin: float) -> tuple[np.ndarray, tuple[float, float]]:
    """占有格子を返す。値は PGM 慣例で 0=占有, 254=空き, 205=未知。"""
    # numpy は生成のときだけ要る。定数と free_bounds() を読むだけの
    # 呼び出し側（テスト）に numpy を要求しないよう、ここで import する。
    import numpy as np

    span_x = length + 2 * margin
    span_y = 2 * half_width + 2 * margin
    cols = int(round(span_x / resolution))
    rows = int(round(span_y / resolution))

    grid = np.full((rows, cols), 205, dtype=np.uint8)

    # 廊下内部を空きにする
    x0 = int(round(margin / resolution))
    x1 = int(round((margin + length) / resolution))
    y0 = int(round(margin / resolution))
    y1 = int(round((margin + 2 * half_width) / resolution))
    grid[y0:y1, x0:x1] = 254

    # 壁を占有にする（内側から wall_thickness ぶん）
    t = max(1, int(round(wall_thickness / resolution)))
    grid[y0:y0 + t, x0:x1] = 0
    grid[y1 - t:y1, x0:x1] = 0
    grid[y0:y1, x0:x0 + t] = 0
    grid[y0:y1, x1 - t:x1] = 0

    # origin は地図左下隅の world 座標。廊下中心を world 原点に置きたいので
    # 半スパンぶん負にずらす。mock_whill_serial の初期姿勢が (0,0) のため。
    origin = (-span_x / 2.0, -span_y / 2.0)
    return grid, origin


def write_pgm(path: Path, grid: np.ndarray) -> None:
    # PGM の行順は上が先。占有格子の y は上向きなので、書き出す前に反転する。
    # np.flipud ではなくスライスにしてあるのは、numpy を build() の中だけの
    # 依存に閉じるため（定数と free_bounds() を読むだけの呼び出し側に
    # numpy を要求しない）。
    flipped = grid[::-1]
    header = f'P5\n# whill_platform mock corridor (generated)\n{grid.shape[1]} {grid.shape[0]}\n255\n'
    with path.open('wb') as handle:
        handle.write(header.encode('ascii'))
        handle.write(flipped.tobytes())


def write_yaml(path: Path, pgm_name: str, resolution: float,
               origin: tuple[float, float]) -> None:
    path.write_text(
        f'# 自動生成: scripts/make_mock_map.py。手で編集しないこと。\n'
        f'image: {pgm_name}\n'
        f'resolution: {resolution}\n'
        f'origin: [{origin[0]:.3f}, {origin[1]:.3f}, 0.0]\n'
        f'negate: 0\n'
        f'occupied_thresh: 0.65\n'
        f'free_thresh: 0.196\n',
        encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description='mock 用の占有格子を生成する')
    parser.add_argument('--half-width', type=float, default=HALF_WIDTH,
                        help='mock_velodyne の corridor_half_width と揃えること')
    parser.add_argument('--length', type=float, default=LENGTH,
                        help='mock_velodyne の corridor_length と揃えること')
    parser.add_argument('--resolution', type=float, default=RESOLUTION,
                        help='params.yaml の costmap resolution と揃えること')
    parser.add_argument('--wall-thickness', type=float, default=WALL_THICKNESS)
    parser.add_argument('--margin', type=float, default=MARGIN,
                        help='廊下の外側に取る未知領域の幅')
    parser.add_argument('--out-dir', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--name', default='mock_corridor')
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    grid, origin = build(args.half_width, args.length, args.resolution,
                         args.wall_thickness, args.margin)
    pgm = args.out_dir / f'{args.name}.pgm'
    write_pgm(pgm, grid)
    write_yaml(args.out_dir / f'{args.name}.yaml', pgm.name, args.resolution, origin)
    print(f'生成: {pgm} ({grid.shape[1]}x{grid.shape[0]} cells, origin={origin})')
    print(f'生成: {args.out_dir / f"{args.name}.yaml"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
