import { applyCostmapUpdate, costmapFromFrame } from './rle'
import type {
  CostmapScope,
  CostmapState,
  DiagnosticEntry,
  ParamChange,
  ParamSpec,
  PathFrame,
  PoseFrame,
  ReplayFrame,
  ScanFrame,
  StackStatus,
  TelemetryDriver,
  TelemetryFrame,
  TelemetryItem,
  TfSummary,
  VirtualObstacle,
} from './types'

/** gateway から届いたフレームを、アプリの状態に落とす。
 *
 * **副作用を持たない純粋な reducer にしてある。** WebSocket も React も
 * 触らないので vitest でそのまま検証できる。フレームの解釈を間違えると
 * 「繋がっているのに画面が更新されない」になるが、その手のバグは
 * ブラウザ越しだと切り分けに時間がかかる。
 *
 * ## 命名の変換
 *
 * gateway は Python 側の慣習で snake_case（`frame_id`, `origin_x`）を送る。
 * web 側は camelCase。**変換はここだけで行う。** 各コンポーネントが
 * 生のフレームを読み始めると、どちらの命名なのかが場所ごとに変わって
 * 事故のもとになる。
 */

/** 受信したまま（snake_case）のフレーム。ここでしか使わない。 */
type WireFrame = Record<string, unknown>

export interface FrameState {
  costmaps: Partial<Record<CostmapScope, CostmapState>>
  pose: PoseFrame | null
  path: PathFrame | null
  scan: ScanFrame | null
  /** いま置かれている仮想障害物。gateway が全量で配る。 */
  obstacles: VirtualObstacle[]
  status: StackStatus | null
  /** bag 再生の位置。replay モード以外では gateway が送ってこないので
   *  null のまま。**null を「0 秒」に潰さないこと。** */
  replay: ReplayFrame | null
  /** ドライバのテレメトリ。閾値の判定は gateway 側で済んでいる。 */
  telemetry: TelemetryFrame | null
  params: ParamSpec[]
  /** registry と実ノードの値がずれているもの。異常なので隠さない。 */
  mismatches: { key: string; registry: unknown; live: unknown }[]
  /** 応答しなかったノード。値は registry のもので代替されている。 */
  unreachable: string[]
  presets: string[]
  appliedPreset: string | null
  /** 変更ログ。受理も拒否も残す。新しいものが先頭。 */
  paramChanges: ParamChange[]
  /** キーごとの「結果が返ってきた回数」。
   *
   * 拒否されたとき、値は変わらないのに入力欄には拒否された値が
   * 残ってしまう（実際は 0.85 なのに 9.9 と表示される）。まさに
   * 「効いたように見えて効いていない」状態なので、結果が返るたびに
   * これを進めて UI 側の下書きを捨てさせる。
   */
  paramRevision: Record<string, number>
  tf: TfSummary | null
  diagnostics: DiagnosticEntry[]
  /** フレーム種別ごとの最終受信時刻 (ms)。古さの判定に使う。 */
  receivedAt: Record<string, number>
  /** gateway から届いたエラー。 */
  lastError: string | null
}

export const emptyFrameState = (): FrameState => ({
  costmaps: {},
  pose: null,
  path: null,
  scan: null,
  obstacles: [],
  status: null,
  replay: null,
  telemetry: null,
  params: [],
  mismatches: [],
  unreachable: [],
  presets: [],
  appliedPreset: null,
  paramChanges: [],
  paramRevision: {},
  tf: null,
  diagnostics: [],
  receivedAt: {},
  lastError: null,
})

export const PARAM_CHANGE_LIMIT = 100
/** 変更ログの保持件数。全部持つ意味は無く、直近が分かればよい。 */

const num = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback

/** 数値か、不明を表す null。既定値で埋めないほうがよい場所に使う。 */
const opt = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const str = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback

/** 1 フレームを適用した新しい状態を返す。
 *
 * 未知の type は無視する（gateway が新しいフレームを足しても古い UI が
 * 壊れないように）。ただし黙って捨てたことが分かるよう、呼び出し側が
 * 数えられる形で false を返す。
 */
export function applyFrame(
  state: FrameState,
  frame: WireFrame,
  now: number,
): { state: FrameState; handled: boolean } {
  const kind = str(frame.type)
  const stamp = { ...state.receivedAt, [kind]: now }

  switch (kind) {
    case 'costmap': {
      const scope = str(frame.scope, 'local') as CostmapScope
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          costmaps: {
            ...state.costmaps,
            [scope]: costmapFromFrame({
              scope,
              frameId: str(frame.frame_id),
              resolution: num(frame.resolution, 0.05),
              width: num(frame.width),
              height: num(frame.height),
              originX: num(frame.origin_x),
              originY: num(frame.origin_y),
              rle: (frame.rle as number[]) ?? [],
              ratio: num(frame.ratio),
              decimation: num(frame.decimation, 1),
              stamp: num(frame.stamp),
              seq: num(frame.seq),
            }),
          },
        },
      }
    }

    case 'costmap_update': {
      const scope = str(frame.scope, 'local') as CostmapScope
      const held = state.costmaps[scope]
      // 全量を持っていない scope の部分更新は貼る先が無い。gateway 側も
      // 送らない建付けだが、順序が入れ替わることはある。
      if (!held) return { state: { ...state, receivedAt: stamp }, handled: true }
      try {
        return {
          handled: true,
          state: {
            ...state,
            receivedAt: stamp,
            costmaps: {
              ...state.costmaps,
              [scope]: applyCostmapUpdate(held, {
                scope,
                x: num(frame.x),
                y: num(frame.y),
                width: num(frame.width),
                height: num(frame.height),
                rle: (frame.rle as number[]) ?? [],
                stamp: num(frame.stamp),
                seq: num(frame.seq),
              }),
            },
          },
        }
      } catch (error) {
        // 貼れない更新は捨てるが、黙らない。ずれた地図で描画を続けるより、
        // 何が起きたか分かるほうがよい。
        return {
          handled: true,
          state: {
            ...state,
            receivedAt: stamp,
            lastError: `costmap の部分更新を貼れない: ${(error as Error).message}`,
          },
        }
      }
    }

    case 'pose':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          pose: {
            x: num(frame.x),
            y: num(frame.y),
            yaw: num(frame.yaw),
            frameId: str(frame.frame_id),
            source: str(frame.source),
            stamp: num(frame.stamp),
          },
        },
      }

    case 'path':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          path: {
            frameId: str(frame.frame_id),
            points: ((frame.points as number[][]) ?? []).map(([x, y]) => ({ x, y })),
            stamp: num(frame.stamp),
          },
        },
      }

    case 'scan':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          scan: {
            frameId: str(frame.frame_id),
            angleMin: num(frame.angle_min),
            angleIncrement: num(frame.angle_increment),
            rangeMax: num(frame.range_max, 100),
            ranges: ((frame.ranges as (number | null)[]) ?? []).map((v) =>
              typeof v === 'number' && Number.isFinite(v) ? v : null,
            ),
            stamp: num(frame.stamp),
          },
        },
      }

    case 'obstacles':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          // 全量置換。差分にすると UI と costmap の状態がずれたときに
          // 復旧できない（gateway 側も同じ方針）。
          obstacles: ((frame.obstacles as WireFrame[]) ?? []).map((raw) => ({
            id: str(raw.id),
            frameId: str(raw.frame_id, 'map'),
            x: num(raw.x),
            y: num(raw.y),
            radius: num(raw.radius),
          })),
        },
      }

    case 'status':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          status: {
            robotId: str(frame.robot_id),
            mode: str(frame.mode, 'mock') as StackStatus['mode'],
            navActive: frame.nav_active === true,
            estop: frame.estop === true,
            clients: num(frame.clients),
            preset: typeof frame.preset === 'string' ? frame.preset : null,
            latencyMs:
              typeof frame.latency_ms === 'number' ? frame.latency_ms : null,
            stamp: num(frame.stamp),
          },
        },
      }

    case 'telemetry':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          telemetry: {
            drivers: ((frame.drivers as WireFrame[]) ?? []).map(toTelemetryDriver),
            stamp: num(frame.stamp),
          },
        },
      }

    case 'replay':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          replay: {
            bag: typeof frame.bag === 'string' ? frame.bag : null,
            // **null を 0 に潰さない。** 不明と「先頭に居る」は別のこと。
            elapsed: opt(frame.elapsed),
            total: opt(frame.total),
            rate: opt(frame.rate),
            playing: frame.playing === true,
            finished: frame.finished === true,
            stamp: num(frame.stamp),
          },
        },
      }

    case 'params':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          params: ((frame.params as WireFrame[]) ?? []).map(toParamSpec),
          mismatches: (frame.mismatches as FrameState['mismatches']) ?? [],
          unreachable: (frame.unreachable as string[]) ?? [],
          presets: (frame.presets as string[]) ?? [],
          appliedPreset:
            typeof frame.preset === 'string' ? frame.preset : null,
        },
      }

    case 'param_changed': {
      const key = str(frame.key)
      const accepted = frame.accepted === true
      const change: ParamChange = {
        key,
        accepted,
        value: frame.value as ParamSpec['value'],
        reason: str(frame.reason),
        stamp: now,
      }
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          // 受理された変更だけ表示値に反映する。拒否されたのに動かすと
          // 「効いたように見えて効いていない」になる。
          params: accepted
            ? state.params.map((spec) =>
                spec.key === key ? { ...spec, value: change.value } : spec,
              )
            : state.params,
          paramChanges: [change, ...state.paramChanges].slice(0, PARAM_CHANGE_LIMIT),
          paramRevision: {
            ...state.paramRevision,
            [key]: (state.paramRevision[key] ?? 0) + 1,
          },
        },
      }
    }

    case 'tf':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          tf: {
            parents: (frame.parents as Record<string, string>) ?? {},
            stamp: num(frame.stamp),
          },
        },
      }

    case 'diagnostics':
      return {
        handled: true,
        state: {
          ...state,
          receivedAt: stamp,
          diagnostics: ((frame.entries as WireFrame[]) ?? []).map((entry) => ({
            name: str(entry.name),
            level: num(entry.level),
            message: str(entry.message),
          })),
        },
      }

    case 'error':
      return {
        handled: true,
        state: { ...state, receivedAt: stamp, lastError: str(frame.reason) },
      }

    case 'hello':
      // 接続の確立は GatewayClient 側で扱う。状態には落とさない。
      return { state, handled: true }

    default:
      return { state, handled: false }
  }
}

function toTelemetryDriver(raw: WireFrame): TelemetryDriver {
  return {
    driver: str(raw.driver),
    expected: raw.expected === true,
    items: ((raw.items as WireFrame[]) ?? []).map(toTelemetryItem),
  }
}

function toTelemetryItem(raw: WireFrame): TelemetryItem {
  return {
    name: str(raw.name),
    driver: str(raw.driver),
    topic: str(raw.topic),
    // **null を 0 に潰さない。** 「不明」と「0」は別のこと。
    value: opt(raw.value),
    unit: typeof raw.unit === 'string' ? raw.unit : null,
    widget: str(raw.widget, 'number') as TelemetryItem['widget'],
    // 不明な level を 'ok' に倒さない。gateway が新しい level を足したときに
    // 「異常なのに緑」になるのが一番まずい。
    level: str(raw.level, 'unknown') as TelemetryItem['level'],
    warn: opt(raw.warn),
    crit: opt(raw.crit),
    compare: str(raw.compare, 'none') as TelemetryItem['compare'],
    description: str(raw.description),
    age: opt(raw.age),
  }
}

function toParamSpec(raw: WireFrame): ParamSpec {
  return {
    key: str(raw.key),
    node: str(raw.node),
    rosNode: str(raw.ros_node),
    name: str(raw.name),
    type: str(raw.type, 'double') as ParamSpec['type'],
    value: raw.value as ParamSpec['value'],
    default: raw.default as ParamSpec['value'],
    range: (raw.range as ParamSpec['range']) ?? null,
    elements: (raw.elements as ParamSpec['elements']) ?? undefined,
    unit: typeof raw.unit === 'string' ? raw.unit : null,
    live: raw.live === true,
    safetyClass: str(raw.safety_class, 'none') as ParamSpec['safetyClass'],
    description: str(raw.description),
  }
}

/** そのフレーム種別が「古い」か。
 *
 * 途絶えたストリームを最新のように描かないための判定。pose が 3 秒来て
 * いないのに車体を最新位置として描くと、実際とずれた絵を信じることになる。
 *
 * 複数の種別を渡せる。costmap は全量と部分更新のどちらが来ても「新しい」
 * ので、両方を見る必要がある（全量を受けた直後に「古い」と判定して
 * 薄く描いてしまう不具合を踏んだ）。
 */
export function isStale(
  receivedAt: Record<string, number>,
  kinds: string | string[],
  now: number,
  thresholdMs: number,
): boolean {
  const list = Array.isArray(kinds) ? kinds : [kinds]
  const latest = list
    .map((kind) => receivedAt[kind])
    .filter((at): at is number => at !== undefined)
  if (latest.length === 0) return true
  return now - Math.max(...latest) > thresholdMs
}

/** costmap の古さを見るときに使う組。全量と部分更新の両方。 */
export const COSTMAP_KINDS = ['costmap', 'costmap_update']
