import { describe, expect, it } from 'vitest'

import { cellColor, decodeRle } from '../src/lib/rle'

describe('decodeRle', () => {
  it('連続値を展開する', () => {
    expect(Array.from(decodeRle([0, 3, 100, 2], 5))).toEqual([0, 0, 0, 100, 100])
  })

  it('未知セル (-1) を保持する', () => {
    expect(Array.from(decodeRle([-1, 2], 2))).toEqual([-1, -1])
  })

  it('期待長に足りないとき失敗する', () => {
    // 静かにゼロ埋めすると、地図の欠けが「空き」に見えて危ない
    expect(() => decodeRle([0, 2], 5)).toThrow(/足りない/)
  })

  it('期待長を超えるとき失敗する', () => {
    expect(() => decodeRle([0, 9], 5)).toThrow(/超えた/)
  })

  it('奇数長の入力を拒否する', () => {
    expect(() => decodeRle([0, 2, 5], 5)).toThrow(/偶数でない/)
  })
})

describe('cellColor', () => {
  it('未知・空き・占有を別の色にする', () => {
    const unknown = cellColor(-1)
    const free = cellColor(0)
    const lethal = cellColor(100)
    expect(unknown).not.toEqual(free)
    expect(free).not.toEqual(lethal)
    expect(unknown).not.toEqual(lethal)
  })
})
