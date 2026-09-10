import type { VirtualObstacle } from './types'

/** 仮想障害物の当たり判定と id の採番。
 *
 * gateway 側の検査（`whill_gateway/obstacles.py`）と数字を揃えること。
 * UI で通しても gateway が弾けば「押したのに置けない」になるだけで、
 * 理由は返るが二度手間。
 */

export const MIN_RADIUS_M = 0.05
export const MAX_RADIUS_M = 5.0
export const MAX_OBSTACLES = 200

/** その world 座標にある障害物を返す。無ければ null。
 *
 * 重なっているときは**小さいほうを優先**する。大きな円の中に小さな円を
 * 置いたとき、大きいほうしか消せないと小さいほうが永久に残る。
 */
export function findObstacleAt(
  obstacles: VirtualObstacle[],
  x: number,
  y: number,
): VirtualObstacle | null {
  const hits = obstacles.filter((o) => {
    const dx = o.x - x
    const dy = o.y - y
    return dx * dx + dy * dy <= o.radius * o.radius
  })
  if (hits.length === 0) return null
  return hits.reduce((best, o) => (o.radius < best.radius ? o : best))
}

/** 新しい id。UI が採番し、gateway はそのまま使う。 */
export function newObstacleId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  // 古いブラウザ向け。衝突しても gateway 側で上書きになるだけなので、
  // 厳密な一意性までは要らない。
  return `vo-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

export function clampRadius(value: number): number {
  return Math.min(MAX_RADIUS_M, Math.max(MIN_RADIUS_M, value))
}
