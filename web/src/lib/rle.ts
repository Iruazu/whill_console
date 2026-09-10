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
