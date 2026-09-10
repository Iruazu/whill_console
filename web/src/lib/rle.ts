import type { CostmapFrame, CostmapState, CostmapUpdateFrame } from './types'

/** costmap の RLE 展開。
 *
 * 転送形式は RLE JSON で開始する（負荷次第で PNG へ切り替える。ADR-0002）。
 * OccupancyGrid の値域は -1 (未知) と 0..100。連続する同値が多いので
 * RLE が効く。ここは gateway 側のエンコーダと対の実装なので、
 * 片方だけ変えないこと。
 */
export function decodeRle(rle: number[], expectedLength: number): Int8Array {
  if (rle.length % 2 !== 0) {
    throw new Error(`RLE の長さが偶数でない: ${rle.length}`)
  }
  const out = new Int8Array(expectedLength)
  let cursor = 0
  for (let i = 0; i < rle.length; i += 2) {
    const value = rle[i]
    const count = rle[i + 1]
    if (count < 0) throw new Error(`RLE の連続数が負: ${count}`)
    const end = cursor + count
    if (end > expectedLength) {
      throw new Error(`RLE が期待長 ${expectedLength} を超えた (${end})`)
    }
    out.fill(value, cursor, end)
    cursor = end
  }
  if (cursor !== expectedLength) {
    throw new Error(`RLE が期待長 ${expectedLength} に足りない (${cursor})`)
  }
  return out
}

/** OccupancyGrid のセル値を描画色に写す。
 *
 * 未知 (-1) を黒でも白でもない灰にするのは、「未知」と「空き」を
 * 目で区別できないと、地図の穴を障害物なしと誤読するため。
 */
export function cellColor(value: number): [number, number, number, number] {
  if (value < 0) return [40, 44, 52, 255]
  if (value >= 99) return [224, 108, 90, 255]
  if (value === 0) return [22, 26, 32, 255]
  const t = value / 100
  const g = Math.round(90 + 100 * (1 - t))
  return [Math.round(60 + 120 * t), g, 110, 255]
}

/** 全量フレームから、手元で保持する格子を作る。 */
export function costmapFromFrame(frame: CostmapFrame): CostmapState {
  return {
    scope: frame.scope,
    frameId: frame.frameId,
    resolution: frame.resolution,
    width: frame.width,
    height: frame.height,
    originX: frame.originX,
    originY: frame.originY,
    cells: decodeRle(frame.rle, frame.width * frame.height),
    decimation: frame.decimation ?? 1,
    seq: frame.seq,
    stamp: frame.stamp,
  }
}

/** 部分更新を貼り込む。
 *
 * gateway 側の `costmap_codec.apply_update` と対の実装。片方だけ変えないこと。
 *
 * 手元の全量より古い更新は捨てる。フレームの順序が入れ替わったときに、
 * 前の格子の断片を新しい格子へ貼って壊れた絵にしないため。
 * 範囲外の更新は例外にする（黙って切り詰めると、ずれた地図で描画が続き
 * 原因を追えない）。
 */
export function applyCostmapUpdate(
  state: CostmapState,
  update: CostmapUpdateFrame,
): CostmapState {
  if (update.scope !== state.scope) {
    throw new Error(`scope が違う: ${update.scope} != ${state.scope}`)
  }
  if (update.seq !== state.seq) {
    // 古い更新。捨てるのが正しく、貼ると壊れる。
    return state
  }
  if (
    update.x < 0 ||
    update.y < 0 ||
    update.x + update.width > state.width ||
    update.y + update.height > state.height
  ) {
    throw new Error(
      `更新矩形 (${update.x},${update.y},${update.width},${update.height}) が ` +
        `格子 ${state.width}x${state.height} の外にはみ出している`,
    )
  }

  const patch = decodeRle(update.rle, update.width * update.height)
  const cells = new Int8Array(state.cells)
  for (let row = 0; row < update.height; row += 1) {
    const start = (update.y + row) * state.width + update.x
    cells.set(patch.subarray(row * update.width, (row + 1) * update.width), start)
  }
  return { ...state, cells, stamp: update.stamp }
}
