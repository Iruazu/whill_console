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


DEFAULT_MAX_CELLS = 250_000
"""1 フレームで送るセル数の上限。

実機のキャンパス地図は **6640 x 6295 = 4180 万セル**（5 cm 解像度）で、
RLE をかけても JSON が約 8 MB になる。ブラウザの WebSocket は既定で
1〜4 MiB を超えるフレームを受け取らず、**接続ごと切れる**（replay モードで
実際に踏んだ: 「gateway は動いているのに 1 通も届かない」）。

俯瞰図は 1000 px 程度の canvas に描く。500x500 もあれば十分で、細かいところは
local costmap（rolling window）で見る。全域の 5 cm 解像度は要らない。
"""


def decimate(cells: list[int], width: int, height: int,
             factor: int) -> tuple[list[int], int, int]:
    """`factor` x `factor` のブロックごとに 1 セルへ間引く。

    **各ブロックの最大値を採る。** 平均だと細い壁が消える — 4180 万セルの
    地図で 1 本の壁が消えれば、そこを通る経路が「通れる」ように見える。

    未知 (-1) は最大値を採れば自然に扱える。ブロック内に既知の値が 1 つでも
    あればそちらが勝ち、全部未知のときだけ -1 が残る。
    """
    if factor <= 1:
        return list(cells), width, height

    out_w = (width + factor - 1) // factor
    out_h = (height + factor - 1) // factor
    out: list[int] = [UNKNOWN] * (out_w * out_h)

    for row in range(height):
        out_row = row // factor
        base = row * width
        out_base = out_row * out_w
        for col in range(width):
            value = cells[base + col]
            index = out_base + col // factor
            if value > out[index]:
                out[index] = value
    return out, out_w, out_h


def decimation_for(width: int, height: int, max_cells: int) -> int:
    """セル数を `max_cells` 以下に収める間引き率。"""
    total = width * height
    if max_cells <= 0 or total <= max_cells:
        return 1
    factor = 1
    while (width + factor - 1) // factor * ((height + factor - 1) // factor) > max_cells:
        factor += 1
    return factor


def costmap_frame(*, scope: str, frame_id: str, resolution: float,
                  width: int, height: int, origin_x: float, origin_y: float,
                  cells: list[int] | bytes, stamp: float, seq: int,
                  max_cells: int = DEFAULT_MAX_CELLS) -> dict[str, Any]:
    """全量フレーム。接続直後の初期表示と、格子が張り替わったときの再同期に使う。

    大きすぎる格子は間引いて送る。**間引いたことをフレームに載せる**ので、
    UI 側は「これは粗い絵だ」と分かる。黙って粗くすると、細かい障害物が
    無いのか間引かれたのかが区別できない。
    """
    signed = [_as_signed(value) for value in cells]
    factor = decimation_for(width, height, max_cells)
    signed, out_w, out_h = decimate(signed, width, height, factor)

    rle = encode_rle(signed)
    return {
        'type': 'costmap',
        'scope': scope,
        'frame_id': frame_id,
        # 間引いたぶん 1 セルの実寸が広がる。原点は左下のままなので動かさない。
        'resolution': resolution * factor,
        'width': out_w,
        'height': out_h,
        'origin_x': origin_x,
        'origin_y': origin_y,
        'rle': rle,
        'ratio': round(compression_ratio(rle, out_w * out_h), 4),
        'decimation': factor,
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
