import { describe, expect, it } from 'vitest'

import {
  LAYOUT_DEFAULTS,
  OPS_MAX_WIDTH,
  isLayout,
  loadLayout,
  opsItems,
  saveLayout,
} from '../src/lib/layout'

/** localStorage の代わり。例外を投げる版も作れるようにしてある。 */
function memoryStorage(initial: Record<string, string> = {}, broken = false): Storage {
  const data = new Map(Object.entries(initial))
  const fail = () => {
    throw new Error('storage is disabled')
  }
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key) => (broken ? fail() : data.get(key) ?? null),
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => (broken ? fail() : void data.set(key, value)),
  }
}

describe('初回のレイアウト', () => {
  it('狭い画面では ops で始める', () => {
    expect(loadLayout(768, memoryStorage())).toBe('ops')
  })

  it('広い画面では dev で始める', () => {
    expect(loadLayout(1440, memoryStorage())).toBe('dev')
  })

  it('境目は OPS_MAX_WIDTH', () => {
    expect(loadLayout(OPS_MAX_WIDTH - 1, memoryStorage())).toBe('ops')
    expect(loadLayout(OPS_MAX_WIDTH, memoryStorage())).toBe('dev')
  })
})

describe('選択の保持', () => {
  it('一度選んだら画面幅より優先する', () => {
    // 見ている最中に画面を回してレイアウトが入れ替わるのは危ない
    const storage = memoryStorage()
    saveLayout('ops', storage)
    expect(loadLayout(1440, storage)).toBe('ops')
    saveLayout('dev', storage)
    expect(loadLayout(768, storage)).toBe('dev')
  })

  it('壊れた値は無視して幅で決める', () => {
    expect(loadLayout(768, memoryStorage({ 'whill.layout': 'tablet' }))).toBe('ops')
  })

  it('storage が使えなくても落ちない', () => {
    // プライベートモード等。操作自体はできるべき
    const broken = memoryStorage({}, true)
    expect(loadLayout(768, broken)).toBe('ops')
    expect(() => saveLayout('dev', broken)).not.toThrow()
  })
})

describe('初期値', () => {
  it('dev は map 固定、ops は追従・進行方向上', () => {
    // 用途が違う: dev は「地図のどこに居るか」、ops は「前に何があるか」
    expect(LAYOUT_DEFAULTS.dev).toMatchObject({ followRobot: false, headingUp: false })
    expect(LAYOUT_DEFAULTS.ops).toMatchObject({ followRobot: true, headingUp: true })
  })

  it('ops ではスライダーを出さない', () => {
    // 現場で 47 本のスライダーは要らない。触れてしまうほうが危ない
    expect(LAYOUT_DEFAULTS.ops.showParams).toBe(false)
    expect(LAYOUT_DEFAULTS.dev.showParams).toBe(true)
  })

  it('カメラは dev だけ（#52）', () => {
    // 運用中に見るものではない。帯域も使う
    expect(LAYOUT_DEFAULTS.dev.showCamera).toBe(true)
    expect(LAYOUT_DEFAULTS.ops.showCamera).toBe(false)
  })

  it('配車はどちらでも出す', () => {
    expect(LAYOUT_DEFAULTS.ops.showDispatch).toBe(true)
    expect(LAYOUT_DEFAULTS.dev.showDispatch).toBe(true)
  })

  it('isLayout は 2 種類だけ通す', () => {
    expect(isLayout('dev')).toBe(true)
    expect(isLayout('ops')).toBe(true)
    expect(isLayout('tablet')).toBe(false)
    expect(isLayout(null)).toBe(false)
  })
})

describe('主要テレメトリ', () => {
  it('設定で ops: true のものだけ残す', () => {
    // どれを主要とするかは cr2-base.yaml が決める。UI に名前を並べない
    const items = [
      { name: 'battery', ops: true },
      { name: 'motor_current_left', ops: false },
      { name: 'scan_rate', ops: true },
    ]
    expect(opsItems(items).map((i) => i.name)).toEqual(['battery', 'scan_rate'])
  })
})
