import { describe, expect, it } from 'vitest'

import {
  MAX_PIXELS_PER_METER,
  MIN_PIXELS_PER_METER,
  canvasToWorld,
  cellToWorld,
  clampZoom,
  defaultView,
  isInsideMap,
  scanToWorld,
  worldToCanvas,
  worldToCell,
} from '../src/lib/transform'

/** 座標変換のテスト。
 *
 * ここを間違えると「だいたい合っているが微妙に違う」絵になる。path だけ
 * 1 セルずれる、LiDAR だけ上下反転する、といった形で出て、原因を追うのが
 * 一番つらい。往復で固める。
 */

const viewport = { width: 800, height: 600 }
const map = { originX: -10, originY: -5, resolution: 0.05, width: 400, height: 200 }

describe('world ↔ canvas', () => {
  it('中心の world 座標は画面中央に来る', () => {
    const view = { ...defaultView(), centerX: 3, centerY: -2 }
    expect(worldToCanvas(3, -2, view, viewport)).toEqual({ x: 400, y: 300 })
  })

  it('canvas の y は下向き、world の y は上向き', () => {
    // ここを取り違えると地図が上下反転する
    const view = defaultView()
    const above = worldToCanvas(0, 1, view, viewport)
    expect(above.y).toBeLessThan(300)
  })

  it('world の x が増えると画面の右へ行く', () => {
    const view = defaultView()
    expect(worldToCanvas(1, 0, view, viewport).x).toBeGreaterThan(400)
  })

  it('往復して元に戻る', () => {
    const view = { centerX: 1.5, centerY: -3.25, pixelsPerMeter: 37, rotation: 0.7 }
    for (const [x, y] of [[0, 0], [4.2, -1.1], [-9, 12.5]]) {
      const canvas = worldToCanvas(x, y, view, viewport)
      const back = canvasToWorld(canvas.x, canvas.y, view, viewport)
      expect(back.x).toBeCloseTo(x, 6)
      expect(back.y).toBeCloseTo(y, 6)
    }
  })

  it('回転しても中心は動かない', () => {
    const view = { ...defaultView(), rotation: 1.2, centerX: 5, centerY: 5 }
    expect(worldToCanvas(5, 5, view, viewport)).toEqual({ x: 400, y: 300 })
  })

  it('90 度回すと前方が上に来る', () => {
    // 「進行方向上」の実装がこれに乗っている
    const view = { ...defaultView(), rotation: -Math.PI / 2 }
    const front = worldToCanvas(1, 0, view, viewport)
    expect(front.y).toBeLessThan(300)
    expect(front.x).toBeCloseTo(400, 6)
  })

  it('ズームすると同じ world 距離が広がる', () => {
    const near = worldToCanvas(1, 0, { ...defaultView(), pixelsPerMeter: 10 }, viewport)
    const far = worldToCanvas(1, 0, { ...defaultView(), pixelsPerMeter: 40 }, viewport)
    expect(far.x - 400).toBeGreaterThan(near.x - 400)
  })
})

describe('world ↔ cell', () => {
  it('セル中心の world 座標を返す', () => {
    expect(cellToWorld(0, 0, map)).toEqual({ x: -9.975, y: -4.975 })
  })

  it('往復して同じセルに戻る', () => {
    for (const [col, row] of [[0, 0], [17, 3], [399, 199]]) {
      const world = cellToWorld(col, row, map)
      expect(worldToCell(world.x, world.y, map)).toEqual({ col, row })
    }
  })

  it('原点そのものは (0, 0) セル', () => {
    expect(worldToCell(map.originX, map.originY, map)).toEqual({ col: 0, row: 0 })
  })

  it('範囲外でも切り詰めず、判定は別に行う', () => {
    // 黙って端に丸めると、地図の外を「端の値」として描いてしまう
    const outside = worldToCell(-100, -100, map)
    expect(outside.col).toBeLessThan(0)
    expect(isInsideMap(outside.col, outside.row, map)).toBe(false)
    expect(isInsideMap(0, 0, map)).toBe(true)
    expect(isInsideMap(400, 0, map)).toBe(false)
  })
})

describe('LiDAR の投影', () => {
  const scan = { angleMin: 0, angleIncrement: Math.PI / 2, ranges: [1, 1, 1, 1] }

  it('pose が無ければ描かない', () => {
    // 原点に置くと「車体の位置に障害物がある」絵になる
    expect(scanToWorld(scan, null)).toEqual([])
  })

  it('車体の向きを足して world に置く', () => {
    const points = scanToWorld(scan, { x: 2, y: 3, yaw: 0 })
    expect(points).toHaveLength(4)
    expect(points[0].x).toBeCloseTo(3, 6)
    expect(points[0].y).toBeCloseTo(3, 6)
    expect(points[1].x).toBeCloseTo(2, 6)
    expect(points[1].y).toBeCloseTo(4, 6)
  })

  it('yaw を足すと点が回る', () => {
    const points = scanToWorld(scan, { x: 0, y: 0, yaw: Math.PI / 2 })
    expect(points[0].x).toBeCloseTo(0, 6)
    expect(points[0].y).toBeCloseTo(1, 6)
  })

  it('null の測距は飛ばす', () => {
    const points = scanToWorld(
      { angleMin: 0, angleIncrement: 1, ranges: [1, null, 2] },
      { x: 0, y: 0, yaw: 0 },
    )
    expect(points).toHaveLength(2)
  })

  it('無限遠を飛ばす', () => {
    const points = scanToWorld(
      { angleMin: 0, angleIncrement: 1, ranges: [Infinity, 1] },
      { x: 0, y: 0, yaw: 0 },
    )
    expect(points).toHaveLength(1)
  })
})

describe('ズームの範囲', () => {
  it('上下限で頭打ちになる', () => {
    expect(clampZoom(0.001)).toBe(MIN_PIXELS_PER_METER)
    expect(clampZoom(100000)).toBe(MAX_PIXELS_PER_METER)
    expect(clampZoom(37)).toBe(37)
  })
})

describe('既定の表示', () => {
  it('回転していない（map 固定）', () => {
    // dev の初期値は追従 OFF・map 固定（計画書 Phase 3）
    expect(defaultView().rotation).toBe(0)
  })
})
