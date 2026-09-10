"""OccupancyGrid の符号化と、部分更新の貼り込み。

**このモジュールは rclpy に依存しない。** 受け取るのは素の数値と配列だけ。
ROS のメッセージ型を直接扱うと、CI で ROS を立てずに検証できなくなる。

Web 側の対の実装は `web/src/lib/rle.ts`。**片方だけ変えないこと**（ADR-0002）。

## なぜ部分更新を扱うのか

Nav2 の `Costmap2DPublisher` は全量を publish し続けない。初回（と格子の
サイズ・原点が変わったとき）だけ latched で出し、以後の変化は
`/…/costmap_updates` に矩形の部分更新として流す。実測（mock 構成、静止、
3 秒間）で全量 1 通に対し部分更新 10 通。

全量だけを見ると「最初の 1 枚のまま固まった地図」を配信することになる。
"""

from __future__ import annotations

from typing import Any

UNKNOWN = -1
"""OccupancyGrid の未知セル。0..100 のコストとは別扱いにする。"""


def encode_rle(cells: list[int] | bytes) -> list[int]:
    """`[値, 連続数, 値, 連続数, ...]` に畳む。

    OccupancyGrid の値域は -1 と 0..100 で、同値が長く続くので RLE がよく効く。
    最悪ケース（1 セルごとに値が変わる）では元の 2 倍になるが、その状況は
    「costmap がノイズだらけ」という別の問題の兆候でもある。
    """
    if not cells:
        return []

    out: list[int] = []
    current = _as_signed(cells[0])
    count = 0
    for raw in cells:
        value = _as_signed(raw)
        if value == current:
            count += 1
            continue
        out.append(current)
        out.append(count)
        current = value
        count = 1
    out.append(current)
    out.append(count)
    return out


def decode_rle(rle: list[int], expected_length: int) -> list[int]:
    """RLE を展開する。長さが合わなければ例外。

    黙ってゼロ埋めしない。地図の欠けが「空き」に見えるのは危険なので、
    壊れているなら壊れていると分かるほうがよい。
    """
    if len(rle) % 2 != 0:
        raise ValueError(f'RLE の長さが偶数でない: {len(rle)}')

    out: list[int] = []
    for index in range(0, len(rle), 2):
        value, count = rle[index], rle[index + 1]
        if count < 0:
            raise ValueError(f'RLE の連続数が負: {count}')
        out.extend([value] * count)
        if len(out) > expected_length:
            raise ValueError(f'RLE が期待長 {expected_length} を超えた ({len(out)})')
    if len(out) != expected_length:
        raise ValueError(f'RLE が期待長 {expected_length} に足りない ({len(out)})')
    return out


def _as_signed(value: int) -> int:
    """OccupancyGrid の data は int8。bytes で来たときに 255 を -1 に戻す。"""
    value = int(value)
    return value - 256 if value > 127 else value


def compression_ratio(rle: list[int], cell_count: int) -> float:
    """RLE 後の要素数 / 元のセル数。1.0 を超えたら逆効果。

    ADR-0002 の「PNG へ切り替えるか」を判断する材料。運用中に監視できるよう
    フレームに載せる。
    """
    if cell_count <= 0:
        return 0.0
    return len(rle) / cell_count


def costmap_frame(*, scope: str, frame_id: str, resolution: float,
                  width: int, height: int, origin_x: float, origin_y: float,
                  cells: list[int] | bytes, stamp: float, seq: int) -> dict[str, Any]:
    """全量フレーム。接続直後の初期表示と、格子が張り替わったときの再同期に使う。"""
    rle = encode_rle(cells)
    return {
        'type': 'costmap',
        'scope': scope,
        'frame_id': frame_id,
        'resolution': resolution,
        'width': width,
        'height': height,
        'origin_x': origin_x,
        'origin_y': origin_y,
        'rle': rle,
        'ratio': round(compression_ratio(rle, width * height), 4),
        'stamp': stamp,
        'seq': seq,
    }


def costmap_update_frame(*, scope: str, x: int, y: int, width: int, height: int,
                         cells: list[int] | bytes, stamp: float,
                         seq: int) -> dict[str, Any]:
    """部分更新フレーム。矩形 (x, y, width, height) を貼り替える。

    `seq` は全量フレームと同じ採番。クライアントは受け取った `seq` が
    自分の持っている全量より古ければ捨てる（順序が入れ替わっても
    壊れた絵にしないため）。
    """
    return {
        'type': 'costmap_update',
        'scope': scope,
        'x': x,
        'y': y,
        'width': width,
        'height': height,
        'rle': encode_rle(cells),
        'stamp': stamp,
        'seq': seq,
    }


def apply_update(grid: list[int], grid_width: int, grid_height: int,
                 *, x: int, y: int, width: int, height: int,
                 cells: list[int]) -> list[int]:
    """保持中の格子に部分更新を貼り込む。新しい配列を返す。

    範囲外の更新は例外にする。黙って切り詰めると、格子と原点がずれた状態で
    描画が続き、「なんとなく合わない地図」になって原因を追えない。
    """
    if len(cells) != width * height:
        raise ValueError(f'更新セル数が {width}x{height} と合わない ({len(cells)})')
    if x < 0 or y < 0 or x + width > grid_width or y + height > grid_height:
        raise ValueError(
            f'更新矩形 ({x},{y},{width},{height}) が格子 '
            f'{grid_width}x{grid_height} の外にはみ出している')
    if len(grid) != grid_width * grid_height:
        raise ValueError(f'格子の長さが {grid_width}x{grid_height} と合わない ({len(grid)})')

    out = list(grid)
    for row in range(height):
        start = (y + row) * grid_width + x
        out[start:start + width] = cells[row * width:(row + 1) * width]
    return out
