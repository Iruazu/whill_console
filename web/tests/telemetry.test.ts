import { describe, expect, it } from 'vitest'

import {
  LEVEL_MARK,
  barRatio,
  formatAge,
  formatValue,
  isDown,
  isOffByDeclaration,
  summaryItems,
  worstLevel,
} from '../src/lib/telemetry'
import type { TelemetryItem, TelemetryLevel } from '../src/lib/types'

/** drivers パネルの表示ロジック。
 *
 * 「どれを赤くするか」を間違えても画面は動いてしまうので、目で見て
 * 気づけない。ここで押さえる。
 */

const item = (over: Partial<TelemetryItem> = {}): TelemetryItem => ({
  name: 'battery',
  driver: 'whill_serial',
  topic: '/whill/states/model_cr2',
  value: 87,
  unit: '%',
  widget: 'bar',
  level: 'ok',
  warn: 30,
  crit: 15,
  compare: 'below',
  description: '',
  ops: false,
  age: 0.4,
  ...over,
})

describe('カードの代表 level', () => {
  it('一番悪いものを採る', () => {
    expect(worstLevel([item({ level: 'ok' }), item({ level: 'warn' })])).toBe('warn')
    expect(worstLevel([item({ level: 'warn' }), item({ level: 'crit' })])).toBe('crit')
  })

  it('unknown より stale を悪いとみなす', () => {
    // 来ていたのに途絶えたのは異常寄り。一度も来ていないのは異常ではない。
    expect(worstLevel([item({ level: 'unknown' }), item({ level: 'stale' })])).toBe('stale')
  })

  it('unknown だけなら unknown', () => {
    // 起動していないドライバまで赤くすると、本当に壊れているものが埋もれる
    expect(worstLevel([item({ level: 'unknown' })])).toBe('unknown')
  })

  it('空なら unknown', () => {
    expect(worstLevel([])).toBe('unknown')
  })
})

describe('起動しているか', () => {
  it('起動するはずなのに全部 unknown なら「起動していない」', () => {
    // 「センサが壊れた」のか「launch に入っていない」のかを切り分けるため
    expect(isDown({
      driver: 'velodyne', expected: true,
      items: [item({ level: 'unknown' }), item({ level: 'unknown' })],
    })).toBe(true)
  })

  it('1 つでも値が来ていれば起動している', () => {
    expect(isDown({
      driver: 'velodyne', expected: true,
      items: [item({ level: 'unknown' }), item({ level: 'ok' })],
    })).toBe(false)
  })

  it('そのモードの対象外なら「起動していない」とは言わない', () => {
    // realsense は既定で起動しない。赤くする理由が無い。
    expect(isDown({
      driver: 'realsense', expected: false,
      items: [item({ level: 'unknown' })],
    })).toBe(false)
  })

  it('項目が無いドライバは判定しない', () => {
    expect(isDown({ driver: 'x', expected: true, items: [] })).toBe(false)
  })
})

describe('畳んだときに出す項目', () => {
  it('先頭の 1 件を出す', () => {
    // 宣言順が重要度の順（battery が先頭）
    const items = [item({ name: 'battery' }), item({ name: 'speed_mode' })]
    expect(summaryItems(items).map((i) => i.name)).toEqual(['battery'])
  })

  it('異常なものは畳んでいても全部出す', () => {
    // 畳んでいるあいだ異常が隠れると、カードを開く理由に気づけない
    const items = [
      item({ name: 'battery', level: 'ok' }),
      item({ name: 'motor_current_left', level: 'warn' }),
      item({ name: 'motor_current_right', level: 'crit' }),
      item({ name: 'speed_mode', level: 'ok' }),
    ]
    expect(summaryItems(items).map((i) => i.name)).toEqual([
      'battery', 'motor_current_left', 'motor_current_right',
    ])
  })

  it('先頭が異常なら重複させない', () => {
    const items = [item({ name: 'battery', level: 'crit' }), item({ name: 'x' })]
    expect(summaryItems(items).map((i) => i.name)).toEqual(['battery'])
  })

  it('途絶えたものも出す', () => {
    const items = [item({ name: 'a', level: 'ok' }), item({ name: 'b', level: 'stale' })]
    expect(summaryItems(items).map((i) => i.name)).toEqual(['a', 'b'])
  })

  it('空でも落ちない', () => {
    expect(summaryItems([])).toEqual([])
  })
})

describe('値の表示', () => {
  it('値が無いことを 0 で描かない', () => {
    // バッテリー 0 % と「バッテリー不明」を同じ絵にするのが一番まずい誤読
    expect(formatValue(item({ value: null }))).toBe('—')
    expect(formatValue(item({ value: 0 }))).toBe('0 %')
  })

  it('単位を添える', () => {
    expect(formatValue(item({ value: 87 }))).toBe('87 %')
    expect(formatValue(item({ value: 34.026, unit: 'degC' }))).toBe('34.03 degC')
  })

  it('単位が無ければ数字だけ', () => {
    expect(formatValue(item({ value: 2, unit: null }))).toBe('2')
  })

  it('大きい数は桁を落とす', () => {
    // points_per_scan は 14400。小数は読みにくいだけ
    expect(formatValue(item({ value: 14400, unit: 'pts' }))).toBe('14400 pts')
  })
})

describe('古さの表示', () => {
  it('秒と分で出す', () => {
    expect(formatAge(4.2)).toBe('4 秒前')
    expect(formatAge(125)).toBe('2 分前')
  })

  it('不明なら何も出さない', () => {
    expect(formatAge(null)).toBe('')
  })
})

describe('色だけで伝えない', () => {
  it('level ごとに文字がある', () => {
    // 屋外のタブレットで輝度と角度に負ける。色覚の差もある
    const levels: TelemetryLevel[] = ['unknown', 'ok', 'stale', 'warn', 'crit']
    for (const level of levels) {
      expect(LEVEL_MARK[level]).toBeTruthy()
    }
    expect(new Set(Object.values(LEVEL_MARK)).size).toBe(levels.length)
  })
})

describe('棒グラフ', () => {
  it('% なら 0..100 で描く', () => {
    expect(barRatio(item({ value: 87 }))).toBeCloseTo(0.87)
  })

  it('範囲外は詰める', () => {
    expect(barRatio(item({ value: 120 }))).toBe(1)
    expect(barRatio(item({ value: -5 }))).toBe(0)
  })

  it('単位が % でなければ棒にしない', () => {
    // 宣言に最大値が無いので目盛りが引けない。目盛りの無い棒は
    // 「半分くらい」という嘘の印象を与える
    expect(barRatio(item({ unit: 'A', value: 4 }))).toBeNull()
  })

  it('widget が bar でなければ棒にしない', () => {
    expect(barRatio(item({ widget: 'number' }))).toBeNull()
  })

  it('値が無ければ棒にしない', () => {
    expect(barRatio(item({ value: null }))).toBeNull()
  })
})

describe('宣言上の対象外（#52）', () => {
  it('起動しない宣言で値も来ていなければ対象外', () => {
    expect(isOffByDeclaration({
      driver: 'realsense', expected: false, items: [item({ level: 'unknown' })],
    })).toBe(true)
  })

  it('宣言上は対象外でも、値が来ていれば普通に出す', () => {
    // --camera で起動したのに「対象外」と出すと、フレームレートが隠れる
    expect(isOffByDeclaration({
      driver: 'realsense', expected: false, items: [item({ level: 'ok' })],
    })).toBe(false)
  })

  it('起動する宣言のドライバは対象外にしない', () => {
    expect(isOffByDeclaration({
      driver: 'velodyne', expected: true, items: [item({ level: 'unknown' })],
    })).toBe(false)
  })
})
