import { describe, expect, it } from 'vitest'

import { formatDuration, formatLatency, formatRate } from '../src/lib/format'

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

describe('再生位置の表示', () => {
  it('分と秒で出す', () => {
    expect(formatDuration(0)).toBe('0:00')
    expect(formatDuration(9)).toBe('0:09')
    expect(formatDuration(75)).toBe('1:15')
    expect(formatDuration(235.08)).toBe('3:55')
  })

  it('不明は数字を出さない', () => {
    // 「不明」と「先頭に居る」を同じ表示にしない
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(NaN)).toBe('—')
  })

  it('負の経過時間は 0 として出す', () => {
    expect(formatDuration(-3)).toBe('0:00')
  })
})

describe('再生速度の表示', () => {
  it('小数 1 桁に丸める', () => {
    // 観測値なので 1.00 ちょうどにはならない。桁を増やすと数字が落ち着かない。
    expect(formatRate(0.98)).toBe('1.0x')
    expect(formatRate(2)).toBe('2.0x')
  })

  it('不明は数字を出さない', () => {
    expect(formatRate(null)).toBe('—')
  })
})
