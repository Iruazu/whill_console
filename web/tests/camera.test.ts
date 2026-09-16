import { describe, expect, it } from 'vitest'

import { RATE_WINDOW_MS, measuredHz, pushArrival } from '../src/lib/camera'

describe('カメラの実測レート（ADR-0007）', () => {
  const stream = (hz: number, count: number, start = 0) =>
    Array.from({ length: count }, (_, i) => start + (i * 1000) / hz)

  it('6 Hz で届けば 6 Hz と出る', () => {
    const times = stream(6, 12)
    expect(measuredHz(times, times[times.length - 1])).toBeCloseTo(6, 1)
  })

  it('1 枚では何も言わない（0 Hz と「まだ来ていない」は別）', () => {
    expect(measuredHz([], 1000)).toBeNull()
    expect(measuredHz([1000], 1000)).toBeNull()
  })

  it('止まったら数字が消える（古い到着は窓から落ちる）', () => {
    const times = stream(6, 12)
    const later = times[times.length - 1] + RATE_WINDOW_MS + 1
    expect(measuredHz(times, later)).toBeNull()
  })

  it('窓の外の到着は捨てる', () => {
    const kept = pushArrival([0, 100], 100 + RATE_WINDOW_MS + 1)
    expect(kept).toEqual([100 + RATE_WINDOW_MS + 1])
  })

  it('設定より遅ければ遅い数字が出る（宣言値を返さない）', () => {
    const times = stream(1, 4)
    expect(measuredHz(times, times[times.length - 1])).toBeCloseTo(1, 1)
  })
})
