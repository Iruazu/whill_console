import { create } from 'zustand'

import { applyFrame, emptyFrameState } from '../lib/frames'
import type { FrameState } from '../lib/frames'
import { LAYOUT_DEFAULTS, loadLayout, saveLayout } from '../lib/layout'
import type { Layout } from '../lib/layout'
import type { ConnectionState } from '../lib/types'

/** 画面全体の状態。
 *
 * フレームの解釈は `lib/frames.ts` の純粋関数に閉じてあり、ここは
 * それを保持して React に配るだけ。store にロジックを足さないこと
 * （足すとテストがブラウザ環境を要求し始める）。
 */
interface ConsoleState extends FrameState {
  connection: ConnectionState
  /** 接続が失敗した理由。黙って繋がらない状態を作らない。 */
  connectionDetail: string
  /** gateway との往復遅延 (ms)。時計合わせが要らないので往復で測る。 */
  latencyMs: number | null
  /** gateway が新しい type を足しても古い UI が壊れないよう無視するが、
   *  無視した数は数える。増え続けているなら UI が古い。 */
  unhandledFrames: number

  /** dev / ops。切り替えは localStorage に残る。 */
  layout: Layout
  /** dev は追従 OFF・map 固定、ops は追従 ON・進行方向上。
   *  用途が違うので初期値も違う（lib/layout.ts）。 */
  followRobot: boolean
  headingUp: boolean

  /** パラメータパネルの絞り込み。camera パネルから「カメラの設定」で
   *  飛ばすために共有する（#53）。**camera 専用のスライダーは作らない。** */
  paramFilter: string

  setConnection: (state: ConnectionState, detail?: string) => void
  setLatency: (ms: number) => void
  ingest: (frame: Record<string, unknown>, now?: number) => void
  setLayout: (layout: Layout) => void
  setFollowRobot: (value: boolean) => void
  setParamFilter: (filter: string) => void
  setHeadingUp: (value: boolean) => void
  clearError: () => void
  reset: () => void
}

const initialLayout: Layout =
  typeof window === 'undefined' ? 'dev' : loadLayout(window.innerWidth)

export const useConsoleStore = create<ConsoleState>((set) => ({
  ...emptyFrameState(),
  connection: 'disconnected',
  connectionDetail: '',
  latencyMs: null,
  unhandledFrames: 0,
  layout: initialLayout,
  followRobot: LAYOUT_DEFAULTS[initialLayout].followRobot,
  headingUp: LAYOUT_DEFAULTS[initialLayout].headingUp,
  paramFilter: '',

  setConnection: (connection, detail = '') =>
    set({
      connection,
      connectionDetail: detail,
      // 切れたら遅延の表示も消す。古い数字が残ると「速い」と誤読する。
      ...(connection === 'connected' ? {} : { latencyMs: null }),
    }),

  setLatency: (latencyMs) => set({ latencyMs }),

  ingest: (frame, now = Date.now()) =>
    set((state) => {
      const { state: next, handled } = applyFrame(state, frame, now)
      return {
        ...next,
        unhandledFrames: handled ? state.unhandledFrames : state.unhandledFrames + 1,
      }
    }),

  // レイアウトを変えたら俯瞰図の見方も既定に戻す。dev の map 固定のまま
  // ops に移ると、現場で「前に何があるか」が見えない画面になる。
  setLayout: (layout) => {
    saveLayout(layout)
    set({
      layout,
      followRobot: LAYOUT_DEFAULTS[layout].followRobot,
      headingUp: LAYOUT_DEFAULTS[layout].headingUp,
    })
  },

  setFollowRobot: (followRobot) => set({ followRobot }),
  setParamFilter: (paramFilter) => set({ paramFilter }),
  setHeadingUp: (headingUp) => set({ headingUp }),
  clearError: () => set({ lastError: null }),

  // 再接続時に古い costmap を引きずらない。前の接続の地図に新しい
  // 部分更新を貼ると壊れた絵になる。
  // レイアウトの選択は接続とは無関係なので残す。
  reset: () => set({ ...emptyFrameState(), unhandledFrames: 0 }),
}))
