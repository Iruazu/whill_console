import { describe, expect, it } from 'vitest'

import { formatLatency } from '../src/lib/format'

describe('遅延の表示', () => {
  it('未測定は数字を出さない', () => {
    // 0 を出すと「速い」と誤読する
    expect(formatLatency(null)).toBe('—')
  })

  it('1 ms 未満は 0 ms と表示しない', () => {
    // localhost では 1 ms を切る。素直に丸めると「0 ms」になり、
    // 未測定や故障と紛らわしい（実際に画面で見て一瞬疑った）。
    expect(formatLatency(0)).toBe('<1 ms')
    expect(formatLatency(0.4)).toBe('<1 ms')
  })

  it('通常の値は整数 ms', () => {
    expect(formatLatency(42)).toBe('42 ms')
    expect(formatLatency(41.6)).toBe('42 ms')
  })
})
