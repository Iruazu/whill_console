import { describe, expect, it } from 'vitest'

import {
  MAX_OBSTACLES,
  MAX_RADIUS_M,
  MIN_RADIUS_M,
  clampRadius,
  findObstacleAt,
  newObstacleId,
} from '../src/lib/obstacles'
import type { VirtualObstacle } from '../src/lib/types'

const circle = (id: string, x: number, y: number, radius: number): VirtualObstacle => ({
  id, frameId: 'map', x, y, radius,
})

describe('当たり判定', () => {
  const list = [circle('a', 0, 0, 1.0), circle('b', 5, 0, 0.5)]

  it('円の中を指すと当たる', () => {
    expect(findObstacleAt(list, 0.5, 0.5)?.id).toBe('a')
  })

  it('円の外は当たらない', () => {
    expect(findObstacleAt(list, 3, 3)).toBeNull()
  })

  it('縁ちょうどは当たる', () => {
    expect(findObstacleAt(list, 1.0, 0)?.id).toBe('a')
  })

  it('重なっているときは小さいほうを優先する', () => {
    // 大きな円の中に小さな円を置いたとき、大きいほうしか消せないと
    // 小さいほうが永久に残る
    const nested = [circle('big', 0, 0, 2.0), circle('small', 0, 0, 0.3)]
    expect(findObstacleAt(nested, 0.1, 0)?.id).toBe('small')
  })

  it('空の一覧では null', () => {
    expect(findObstacleAt([], 0, 0)).toBeNull()
  })
})

describe('半径の範囲', () => {
  it('上下限で頭打ちになる', () => {
    expect(clampRadius(0.001)).toBe(MIN_RADIUS_M)
    expect(clampRadius(999)).toBe(MAX_RADIUS_M)
    expect(clampRadius(0.6)).toBe(0.6)
  })

  it('gateway 側と同じ数字を使う', () => {
    // 食い違うと「UI では置けたのに gateway に弾かれる」ことになる。
    // gateway 側は whill_gateway/obstacles.py の MIN/MAX_RADIUS_M。
    expect(MIN_RADIUS_M).toBe(0.05)
    expect(MAX_RADIUS_M).toBe(5.0)
    expect(MAX_OBSTACLES).toBe(200)
  })
})

describe('id の採番', () => {
  it('毎回違う', () => {
    const ids = new Set(Array.from({ length: 50 }, () => newObstacleId()))
    expect(ids.size).toBe(50)
  })

  it('空でない文字列', () => {
    expect(newObstacleId().length).toBeGreaterThan(0)
  })
})
