import { applyCostmapUpdate, costmapFromFrame } from './rle'
import type {
  CostmapScope,
  CostmapState,
  DiagnosticEntry,
  ParamChange,
  ParamSpec,
  PathFrame,
  PoseFrame,
  StackStatus,
  TfSummary,
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
  status: StackStatus | null
  params: ParamSpec[]
  /** registry と実ノードの値がずれているもの。異常なので隠さない。 */
  mismatches: { key: string; registry: unknown; live: unknown }[]
  /** 応答しなかったノード。値は registry のもので代替されている。 */
  unreachable: string[]
  presets: string[]
  appliedPreset: string | null
  /** 変更ログ。受理も拒否も残す。新しいものが先頭。 */
  paramChanges: ParamChange[]
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
  status: null,
  params: [],
  mismatches: [],
  unreachable: [],
  presets: [],
  appliedPreset: null,
  paramChanges: [],
  tf: null,
  diagnostics: [],
  receivedAt: {},
  lastError: null,
})

export const PARAM_CHANGE_LIMIT = 100
/** 変更ログの保持件数。全部持つ意味は無く、直近が分かればよい。 */

const num = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback

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
 */
export function isStale(
  state: FrameState,
  kind: string,
  now: number,
  thresholdMs: number,
): boolean {
  const at = state.receivedAt[kind]
  if (at === undefined) return true
  return now - at > thresholdMs
}
