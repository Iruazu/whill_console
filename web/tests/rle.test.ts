import { describe, expect, it } from 'vitest'

import { applyCostmapUpdate, cellColor, costmapFromFrame, decodeRle } from '../src/lib/rle'
import type { CostmapFrame } from '../src/lib/types'

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

describe('costmap の部分更新', () => {
  const full = (): CostmapFrame => ({
    scope: 'local',
    frameId: 'map',
    resolution: 0.05,
    width: 4,
    height: 4,
    originX: -1,
    originY: -1,
    rle: [0, 16],
    ratio: 0.125,
    decimation: 1,
    stamp: 1,
    seq: 5,
  })

  it('全量フレームから格子を作る', () => {
    const state = costmapFromFrame(full())
    expect(state.cells.length).toBe(16)
    expect(state.seq).toBe(5)
    expect(state.resolution).toBe(0.05)
  })

  it('矩形を貼り替える', () => {
    const state = costmapFromFrame(full())
    const patched = applyCostmapUpdate(state, {
      scope: 'local',
      x: 1,
      y: 1,
      width: 2,
      height: 2,
      rle: [100, 4],
      stamp: 2,
      seq: 5,
    })
    expect(Array.from(patched.cells)).toEqual([
      0, 0, 0, 0,
      0, 100, 100, 0,
      0, 100, 100, 0,
      0, 0, 0, 0,
    ])
  })

  it('元の格子を書き換えない', () => {
    const state = costmapFromFrame(full())
    applyCostmapUpdate(state, {
      scope: 'local', x: 0, y: 0, width: 1, height: 1,
      rle: [100, 1], stamp: 2, seq: 5,
    })
    expect(Array.from(state.cells)).toEqual(new Array(16).fill(0))
  })

  it('古い seq の更新は捨てる', () => {
    // 貼ると前の格子の断片が新しい格子に混ざって壊れた絵になる
    const state = costmapFromFrame(full())
    const result = applyCostmapUpdate(state, {
      scope: 'local', x: 0, y: 0, width: 1, height: 1,
      rle: [100, 1], stamp: 2, seq: 4,
    })
    expect(result).toBe(state)
  })

  it('範囲外の更新を拒否する', () => {
    const state = costmapFromFrame(full())
    expect(() =>
      applyCostmapUpdate(state, {
        scope: 'local', x: 3, y: 3, width: 2, height: 2,
        rle: [0, 4], stamp: 2, seq: 5,
      }),
    ).toThrow(/はみ出している/)
  })

  it('scope 違いを拒否する', () => {
    const state = costmapFromFrame(full())
    expect(() =>
      applyCostmapUpdate(state, {
        scope: 'global', x: 0, y: 0, width: 1, height: 1,
        rle: [0, 1], stamp: 2, seq: 5,
      }),
    ).toThrow(/scope が違う/)
  })

  it('積み重ねた更新が全量の受け直しと一致する', () => {
    // gateway 側 test_patched_grid_matches_a_fresh_full_grid と対のテスト。
    // ここが割れると UI の地図が実際の costmap と静かにずれていく。
    let state = costmapFromFrame(full())
    const truth = new Array<number>(16).fill(0)
    const patches: [number, number, number, number, number[]][] = [
      [0, 0, 2, 1, [100, 100]],
      [2, 2, 2, 2, [50, 50, 50, 50]],
      [1, 3, 1, 1, [-1]],
    ]
    for (const [x, y, w, h, cells] of patches) {
      const rle: number[] = []
      for (const v of cells) rle.push(v, 1)
      state = applyCostmapUpdate(state, {
        scope: 'local', x, y, width: w, height: h, rle, stamp: 9, seq: 5,
      })
      for (let row = 0; row < h; row += 1) {
        for (let col = 0; col < w; col += 1) {
          truth[(y + row) * 4 + x + col] = cells[row * w + col]
        }
      }
    }
    expect(Array.from(state.cells)).toEqual(truth)
  })
})
