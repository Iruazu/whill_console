/** gateway ↔ web の共有型。Phase 2 で gateway 側の実装と対にする。 */

export type Mode = 'real' | 'sim' | 'mock' | 'replay'
export type SafetyClass = 'none' | 'caution' | 'locked_while_moving'
export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface ParamSpec {
  key: string
  node: string
  /** 実行時の ROS ノード名。yaml のキーとは違うことがある
   *  （Nav2 の costmap は `local_costmap` に対し `/local_costmap/local_costmap`）。 */
  rosNode: string
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

export type CostmapScope = 'local' | 'global'

/** 全量。接続直後と、格子が張り替わったときだけ来る。
 *
 * Nav2 は全量を publish し続けない。以後の変化は CostmapUpdateFrame として
 * 部分更新で来るので、両方を扱わないと地図が固まる（ADR-0002）。
 */
export interface CostmapFrame {
  scope: CostmapScope
  frameId: string
  resolution: number
  width: number
  height: number
  originX: number
  originY: number
  /** RLE。[値, 連続数] の並び。転送形式の決定は ADR-0002 を参照。 */
  rle: number[]
  /** RLE 後の要素数 / セル数。1 を超えたら RLE が逆効果になっている。 */
  ratio: number
  stamp: number
  seq: number
}

/** 矩形 (x, y, width, height) の部分更新。 */
export interface CostmapUpdateFrame {
  scope: CostmapScope
  x: number
  y: number
  width: number
  height: number
  rle: number[]
  stamp: number
  /** どの全量に対する更新か。手元の全量より古ければ捨てる。 */
  seq: number
}

/** 手元で保持する格子。全量を受けて作り、部分更新で貼り替えていく。 */
export interface CostmapState {
  scope: CostmapScope
  frameId: string
  resolution: number
  width: number
  height: number
  originX: number
  originY: number
  cells: Int8Array
  seq: number
  stamp: number
}

export interface PoseFrame {
  x: number
  y: number
  yaw: number
  frameId: string
  /** 実機は scan-to-map localizer の pcl_pose、mock は EKF の odometry/filtered。 */
  source: string
  stamp: number
}

export interface PathFrame {
  frameId: string
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
  clients: number
  /** 適用中の preset。全部が受理されたときだけ入る。 */
  preset: string | null
  stamp: number
}

/** パラメータ変更の結果。**拒否も残す。**
 *
 * 受理だけ記録すると「UI で動かしたのに変わらなかった」原因が追えない。
 */
export interface ParamChange {
  key: string
  accepted: boolean
  value: ParamSpec['value']
  /** 拒否の理由（範囲外・型違い・走行中・再起動が必要）。 */
  reason: string
  stamp: number
}

/** tf ツリーの要約。変換行列そのものは送られてこない（3D は Foxglove に委譲）。 */
export interface TfSummary {
  /** child → parent。 */
  parents: Record<string, string>
  stamp: number
}

export interface DiagnosticEntry {
  name: string
  /** 0=OK, 1=WARN, 2=ERROR, 3=STALE (diagnostic_msgs の慣習)。 */
  level: number
  message: string
}
