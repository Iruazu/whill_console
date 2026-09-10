/** gateway ↔ web の共有型。Phase 2 で gateway 側の実装と対にする。 */

export type Mode = 'real' | 'sim' | 'mock' | 'replay'
export type SafetyClass = 'none' | 'caution' | 'locked_while_moving'
export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface ParamSpec {
  key: string
  node: string
  name: string
  type: 'double' | 'int' | 'bool' | 'string' | 'double_array'
  value: number | boolean | string | number[]
  default: number | boolean | string | number[]
  range: { min?: number; max?: number; step?: number } | null
  /** double_array の軸ごとの定義。差動二輪の vy のように軸で範囲が違うため。 */
  elements?: { label: string; range?: { min?: number; max?: number; step?: number } }[]
  unit: string | null
  live: boolean
  safetyClass: SafetyClass
  description: string
}

export interface CostmapFrame {
  frameId: string
  resolution: number
  width: number
  height: number
  originX: number
  originY: number
  /** RLE。[値, 連続数] の並び。転送形式の決定は ADR-0002 を参照。 */
  rle: number[]
  stamp: number
}

export interface PoseFrame {
  x: number
  y: number
  yaw: number
  stamp: number
}

export interface PathFrame {
  points: { x: number; y: number }[]
  stamp: number
}

export interface StackStatus {
  robotId: string
  mode: Mode
  navActive: boolean
  /** gateway が測った往復遅延 (ms)。上部帯に出す。 */
  latencyMs: number | null
  estop: boolean
}
