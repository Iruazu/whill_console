import type { TelemetryDriver, TelemetryItem, TelemetryLevel } from './types'

/** drivers パネルの表示ロジック。
 *
 * **純粋関数だけ置く。** React も DOM も触らないので vitest でそのまま
 * 検証できる。この手の「どれを赤くするか」は間違えても画面が動いてしまう
 * ぶん、目で見て気づけない。
 *
 * ## 閾値をここで評価しないこと
 *
 * `level` は gateway が付けたものをそのまま使う。UI 側で warn / crit を
 * 見直すと、`whill doctor` や CLI から見たときに画面と違う答えが出る
 * （閾値を読む場所は 1 つ、#39 で決めた）。
 */

/** 悪いほうが大きい。カードの代表 level を決めるのに使う。
 *
 * `unknown` を最下位に置くのは、値が来ていないことを「異常」として
 * 赤くしないため。起動していないドライバまで赤くすると、本当に壊れている
 * ものが埋もれる。ただし `stale`（来ていたのに途絶えた）は異常寄りに置く。
 */
const RANK: Record<TelemetryLevel, number> = {
  unknown: 0,
  ok: 1,
  stale: 2,
  warn: 3,
  crit: 4,
}

/** そのドライバの代表 level。中で一番悪いもの。 */
export function worstLevel(items: TelemetryItem[]): TelemetryLevel {
  return items.reduce<TelemetryLevel>(
    (worst, item) => (RANK[item.level] > RANK[worst] ? item.level : worst),
    'unknown',
  )
}

/** そのドライバが「起動していない」か。
 *
 * **「値が無い」と「そもそも起動していない」を区別する。** これが付かないと、
 * 現地で「センサが壊れた」のか「launch に入っていない」のかを切り分けられず、
 * 見当違いのところを探すことになる。
 *
 * 宣言されていない（`expected: false`）ドライバは、起動していなくて当たり前
 * なので該当しない（realsense は既定で起動しない）。
 */
export function isDown(driver: TelemetryDriver): boolean {
  return (
    driver.expected &&
    driver.items.length > 0 &&
    driver.items.every((item) => item.level === 'unknown')
  )
}

/** そのモードでは起動しない宣言で、実際にも値が来ていないか（「対象外」と出す）。
 *
 * **宣言上は対象外でも、値が来ていれば普通に出す**（#52）。realsense は既定で
 * 起動しないが、`--camera` を付ければ動く。動いているのに「対象外」と出すと、
 * フレームレートのテレメトリが隠れる。
 */
export function isOffByDeclaration(driver: TelemetryDriver): boolean {
  return !driver.expected && driver.items.every((item) => item.level === 'unknown')
}

/** 畳んだ状態で出す項目。
 *
 * 先頭の 1 件（宣言順が重要度の順）に加えて、**warn / crit / stale のものは
 * 全部出す。** 畳んでいるあいだ異常が隠れると、カードを開く理由に気づけない。
 */
export function summaryItems(items: TelemetryItem[]): TelemetryItem[] {
  const notable = items.filter((item) => RANK[item.level] >= RANK.stale)
  const head = items.length > 0 && !notable.includes(items[0]) ? [items[0]] : []
  return [...head, ...notable]
}

/** 値の表示。**値が無いことを 0 で描かない。**
 *
 * バッテリー 0 % と「バッテリー不明」を同じ絵にするのが、この画面で
 * 作りうる一番まずい誤読。
 */
export function formatValue(item: TelemetryItem): string {
  if (item.value === null) return '—'
  const digits = Math.abs(item.value) >= 100 ? 0 : item.value % 1 === 0 ? 0 : 2
  const text = item.value.toFixed(digits)
  return item.unit ? `${text} ${item.unit}` : text
}

/** 古さの表示。stale のときだけ意味がある。 */
export function formatAge(age: number | null): string {
  if (age === null) return ''
  if (age < 60) return `${Math.round(age)} 秒前`
  return `${Math.round(age / 60)} 分前`
}

/** level を文字でも出す。
 *
 * **色だけで伝えない。** 屋外のタブレットで見る前提があり、輝度と角度で
 * 色は当てにならない。色覚の差もある。
 */
export const LEVEL_MARK: Record<TelemetryLevel, string> = {
  unknown: '—',
  ok: 'OK',
  stale: '古',
  warn: '注意',
  crit: '異常',
}

/** `widget: bar` を実際に棒で描けるか。
 *
 * 宣言には最大値が無い（`cr2-base.yaml` の telemetry は warn / crit しか
 * 持たない）ので、**0..100 と分かっているものだけ棒にする。** 目盛りの
 * 無い棒は「半分くらい」という嘘の印象を与える。それ以外は数字で出す。
 */
export function barRatio(item: TelemetryItem): number | null {
  if (item.widget !== 'bar' || item.value === null) return null
  if (item.unit !== '%') return null
  return Math.max(0, Math.min(1, item.value / 100))
}
