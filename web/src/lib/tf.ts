/** tf パネルの組み立て（#51）。
 *
 * **純粋関数だけ置く。** 辺ごとの判定（古さ・閾値）は gateway が済ませてある
 * （`whill_gateway/tf_tree.py`）。ここでは木に並べることと、全体を一言で
 * まとめることだけをする。
 *
 * ## 全体の判定
 *
 * - 異常: 宣言した動的な辺が crit、または来ていない
 *   （`map -> odom` が無い = 自分の位置が分からない。Nav2 が止まる）
 * - 注意: 宣言した動的な辺が warn、木が分かれている、静的な辺が宣言と違う
 *
 * 静的な辺の食い違いを異常にしないのは、走行中に起きる故障ではなく設定と
 * 実機の差だから。いま止まる話ではないが、見えないと気づけない。
 */

import type { TfEdge, TfMissing, TfSummary } from './types'

export type TfHealthLevel = 'ok' | 'warn' | 'crit'

export interface TfHealth {
  level: TfHealthLevel
  /** 何が起きているかの一言。ok なら空。 */
  reasons: string[]
}

export interface TfNode {
  frame: string
  /** 親からこのフレームへの辺。根は null。 */
  edge: TfEdge | null
  children: TfNode[]
}

export const TF_HEALTH_MARK: Record<TfHealthLevel, string> = {
  ok: 'OK',
  warn: '注意',
  crit: '異常',
}

export const TF_EDGE_MARK: Record<TfEdge['level'], string> = {
  ok: 'OK',
  warn: '注意',
  crit: '異常',
  static: '静的',
  unjudged: '—',
}

function edgeName(edge: { parent: string; child: string }): string {
  return `${edge.parent} → ${edge.child}`
}

function missingReason(missing: TfMissing): string {
  const who = missing.source ? `（${missing.source}）` : ''
  if (missing.actual_parent !== null) {
    return `${edgeName(missing)} の親が ${missing.actual_parent} になっている${who}`
  }
  return `${edgeName(missing)} が来ていない${who}`
}

export function tfHealth(summary: TfSummary): TfHealth {
  const crit: string[] = []
  const warn: string[] = []

  for (const edge of summary.edges) {
    if (!edge.expected || edge.static) continue
    const who = edge.source ? `（${edge.source}）` : ''
    const age = edge.age === null ? '' : ` ${edge.age.toFixed(1)} 秒`
    if (edge.level === 'crit') crit.push(`${edgeName(edge)} が止まっている${age}${who}`)
    else if (edge.level === 'warn') warn.push(`${edgeName(edge)} が遅れている${age}${who}`)
  }
  for (const missing of summary.missing) {
    // 動的な辺は、無ければ位置が分からない。静的な辺は設定と実機の食い違い。
    ;(missing.kind === 'dynamic' ? crit : warn).push(missingReason(missing))
  }
  if (summary.roots.length > 1) {
    warn.push(`木が ${summary.roots.length} つに分かれている（根: ${summary.roots.join(', ')}）`)
  }

  const level: TfHealthLevel = crit.length > 0 ? 'crit' : warn.length > 0 ? 'warn' : 'ok'
  return { level, reasons: [...crit, ...warn] }
}

/** 根から辿れる木に並べる。子は名前順（届いた順だと表示が揺れる）。
 *
 * 循環していても止まるように、辿ったフレームは二度と辿らない。tf の仕様上
 * 循環は起きないはずだが、壊れたデータで画面ごと固まるのは困る。
 */
export function buildTfTree(summary: TfSummary): TfNode[] {
  const byParent = new Map<string, TfEdge[]>()
  for (const edge of summary.edges) {
    const list = byParent.get(edge.parent) ?? []
    list.push(edge)
    byParent.set(edge.parent, list)
  }
  const seen = new Set<string>()

  const build = (frame: string, edge: TfEdge | null): TfNode => {
    seen.add(frame)
    const children = (byParent.get(frame) ?? [])
      .filter((child) => !seen.has(child.child))
      .sort((a, b) => a.child.localeCompare(b.child))
      .map((child) => build(child.child, child))
    return { frame, edge, children }
  }

  return [...summary.roots].sort().map((root) => build(root, null))
}

/** 辺の横に出す文字。静的は古さを出さない（止まっていて正常。印は badge が出す）。 */
export function edgeDetail(edge: TfEdge): string {
  if (edge.static) return edge.expected ? '' : '宣言外'
  const parts: string[] = []
  if (edge.rate_hz !== null) parts.push(`${edge.rate_hz.toFixed(1)} Hz`)
  if (edge.age !== null && (edge.level === 'warn' || edge.level === 'crit' || edge.age >= 1)) {
    parts.push(`${edge.age.toFixed(1)} 秒前`)
  }
  if (!edge.expected) parts.push('宣言外')
  return parts.join(' / ')
}
