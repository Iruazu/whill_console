import type { CostmapState } from './types'

/** 俯瞰図の座標変換。
 *
 * **変換はここだけに置く。** 描画コードに散らすと、path だけ 1 セルずれる、
 * LiDAR だけ上下反転する、といった「だいたい合っているが微妙に違う」絵に
 * なる。原因を追うのが一番つらい種類のバグなので、単体テストで固める。
 *
 * ## 3 つの座標系
 *
 *   world  … ROS の map 座標 (m)。右手系で x 前・y 左・yaw は反時計回り
 *   cell   … OccupancyGrid の格子。原点は左下、行は下から上
 *   canvas … 画面 (px)。原点は左上、y は下向き
 *
 * canvas だけ y が逆を向いている。ここを取り違えると地図が上下反転する。
 */

export interface ViewState {
  /** 画面中心が指す world 座標 (m)。 */
  centerX: number
  centerY: number
  /** 1 m を何 px で描くか。 */
  pixelsPerMeter: number
  /** 画面を回す角度 (rad)。進行方向上のとき車体の yaw を入れる。 */
  rotation: number
}

export const defaultView = (): ViewState => ({
  centerX: 0,
  centerY: 0,
  // 20 px/m = 0.05 m の costmap セルが 1 px。等倍から始める。
  pixelsPerMeter: 20,
  rotation: 0,
})

export const MIN_PIXELS_PER_METER = 2
export const MAX_PIXELS_PER_METER = 200

export interface Viewport {
  width: number
  height: number
}

/** world (m) → canvas (px)。 */
export function worldToCanvas(
  x: number,
  y: number,
  view: ViewState,
  viewport: Viewport,
): { x: number; y: number } {
  const dx = x - view.centerX
  const dy = y - view.centerY

  // 画面を rotation だけ回す = 点を -rotation 回す
  const cos = Math.cos(-view.rotation)
  const sin = Math.sin(-view.rotation)
  const rx = dx * cos - dy * sin
  const ry = dx * sin + dy * cos

  return {
    x: viewport.width / 2 + rx * view.pixelsPerMeter,
    // canvas の y は下向き。world の y は上向き。符号を反転する。
    y: viewport.height / 2 - ry * view.pixelsPerMeter,
  }
}

/** canvas (px) → world (m)。クリック位置から world を求めるのに使う
 *  （Phase 4 の仮想障害物の配置）。 */
export function canvasToWorld(
  px: number,
  py: number,
  view: ViewState,
  viewport: Viewport,
): { x: number; y: number } {
  const rx = (px - viewport.width / 2) / view.pixelsPerMeter
  const ry = -(py - viewport.height / 2) / view.pixelsPerMeter

  const cos = Math.cos(view.rotation)
  const sin = Math.sin(view.rotation)
  const dx = rx * cos - ry * sin
  const dy = rx * sin + ry * cos

  return { x: dx + view.centerX, y: dy + view.centerY }
}

/** cell → world。セルの中心を返す。 */
export function cellToWorld(
  col: number,
  row: number,
  map: Pick<CostmapState, 'originX' | 'originY' | 'resolution'>,
): { x: number; y: number } {
  return {
    x: map.originX + (col + 0.5) * map.resolution,
    y: map.originY + (row + 0.5) * map.resolution,
  }
}

/** world → cell。範囲外でも切り詰めずに返す（呼び出し側が判断する）。 */
export function worldToCell(
  x: number,
  y: number,
  map: Pick<CostmapState, 'originX' | 'originY' | 'resolution'>,
): { col: number; row: number } {
  return {
    col: Math.floor((x - map.originX) / map.resolution),
    row: Math.floor((y - map.originY) / map.resolution),
  }
}

export function isInsideMap(
  col: number,
  row: number,
  map: Pick<CostmapState, 'width' | 'height'>,
): boolean {
  return col >= 0 && row >= 0 && col < map.width && row < map.height
}

/** LiDAR の 1 スキャンを world 座標の点列に直す。
 *
 * scan は車体（`frame_id`）基準なので、pose で world へ移す。pose が無ければ
 * 描かない — 原点に置くと「車体の位置に障害物がある」絵になる。
 */
export function scanToWorld(
  scan: { angleMin: number; angleIncrement: number; ranges: (number | null)[] },
  pose: { x: number; y: number; yaw: number } | null,
): { x: number; y: number }[] {
  if (!pose) return []
  const points: { x: number; y: number }[] = []
  for (let i = 0; i < scan.ranges.length; i += 1) {
    const range = scan.ranges[i]
    if (range === null || !Number.isFinite(range)) continue
    const angle = scan.angleMin + i * scan.angleIncrement + pose.yaw
    points.push({
      x: pose.x + range * Math.cos(angle),
      y: pose.y + range * Math.sin(angle),
    })
  }
  return points
}

export function clampZoom(value: number): number {
  return Math.min(MAX_PIXELS_PER_METER, Math.max(MIN_PIXELS_PER_METER, value))
}
