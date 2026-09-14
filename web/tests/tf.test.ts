import { describe, expect, it } from 'vitest'

import { buildTfTree, edgeDetail, tfHealth } from '../src/lib/tf'
import type { TfEdge, TfSummary } from '../src/lib/types'

function edge(parent: string, child: string, over: Partial<TfEdge> = {}): TfEdge {
  return {
    parent, child, static: false, expected: true, source: '', age: 0.05, rate_hz: 10,
    level: 'ok', ...over,
  }
}

function summary(over: Partial<TfSummary> = {}): TfSummary {
  const edges = over.edges ?? [
    edge('map', 'odom', { source: 'localizer' }),
    edge('odom', 'base_link', { source: 'EKF', rate_hz: 30 }),
    edge('base_link', 'imu_link', { static: true, age: null, rate_hz: null, level: 'static' }),
  ]
  return {
    parents: Object.fromEntries(edges.map((e) => [e.child, e.parent])),
    edges,
    roots: ['map'],
    missing: [],
    stamp: 0,
    ...over,
  }
}

describe('tf の全体の判定（#51）', () => {
  it('健全なら OK で理由なし', () => {
    expect(tfHealth(summary())).toEqual({ level: 'ok', reasons: [] })
  })

  it('localizer が止まったら異常。どの辺で誰が出すものかを言う', () => {
    const h = tfHealth(summary({ edges: [
      edge('map', 'odom', { source: 'localizer', level: 'crit', age: 3.4, rate_hz: null }),
    ] }))
    expect(h.level).toBe('crit')
    expect(h.reasons[0]).toContain('map → odom')
    expect(h.reasons[0]).toContain('localizer')
    expect(h.reasons[0]).toContain('3.4 秒')
  })

  it('遅れは注意', () => {
    const h = tfHealth(summary({ edges: [edge('map', 'odom', { level: 'warn', age: 1.2 })] }))
    expect(h.level).toBe('warn')
  })

  it('来ていない動的な辺は異常（位置が分からない）', () => {
    const h = tfHealth(summary({
      roots: ['odom'],
      edges: [edge('odom', 'base_link')],
      missing: [{ parent: 'map', child: 'odom', kind: 'dynamic', source: 'localizer', actual_parent: null }],
    }))
    expect(h.level).toBe('crit')
    expect(h.reasons[0]).toBe('map → odom が来ていない（localizer）')
  })

  it('静的な辺の親の食い違いは注意（設定と実機の差）', () => {
    const h = tfHealth(summary({
      missing: [{ parent: 'velodyne', child: 'camera_link', kind: 'static', source: '',
        actual_parent: 'base_link' }],
    }))
    expect(h.level).toBe('warn')
    expect(h.reasons[0]).toContain('親が base_link')
  })

  it('宣言外の辺は古くても判定しない', () => {
    const h = tfHealth(summary({ edges: [
      ...summary().edges,
      edge('base_link', 'wheel', { expected: false, level: 'unjudged', age: 60, rate_hz: null }),
    ] }))
    expect(h.level).toBe('ok')
  })

  it('木が分かれていたら注意', () => {
    expect(tfHealth(summary({ roots: ['map', 'world'] })).level).toBe('warn')
  })
})

describe('木に並べる', () => {
  it('根から辿り、子は名前順', () => {
    const [root] = buildTfTree(summary({ edges: [
      edge('map', 'odom'),
      edge('odom', 'base_link'),
      edge('base_link', 'velodyne', { static: true, level: 'static' }),
      edge('base_link', 'imu_link', { static: true, level: 'static' }),
    ] }))
    expect(root.frame).toBe('map')
    const base = root.children[0].children[0]
    expect(base.frame).toBe('base_link')
    expect(base.children.map((n) => n.frame)).toEqual(['imu_link', 'velodyne'])
  })

  it('壊れたデータで循環していても止まる', () => {
    const trees = buildTfTree(summary({
      roots: ['a'],
      edges: [edge('a', 'b'), edge('b', 'a')],
    }))
    expect(trees[0].children[0].frame).toBe('b')
    expect(trees[0].children[0].children).toEqual([])
  })
})

describe('辺の横の文字', () => {
  it('静的な辺は古さを出さない', () => {
    expect(edgeDetail(edge('base_link', 'imu_link', { static: true, age: null, level: 'static' })))
      .toBe('')
    expect(edgeDetail(edge('base_link', 'cam', { static: true, expected: false, level: 'static' })))
      .toBe('宣言外')
  })

  it('止まった辺はレートを出さず、何秒前かを出す', () => {
    expect(edgeDetail(edge('map', 'odom', { level: 'crit', age: 3.44, rate_hz: null })))
      .toBe('3.4 秒前')
  })

  it('健全な辺はレートだけ', () => {
    expect(edgeDetail(edge('odom', 'base_link', { rate_hz: 30 }))).toBe('30.0 Hz')
  })
})
