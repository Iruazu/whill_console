import { create } from 'zustand'

import { applyFrame, emptyFrameState, isStale } from '../lib/frames'
import type { FrameState } from '../lib/frames'
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
  /** gateway が新しい type を足しても古い UI が壊れないよう無視するが、
   *  無視した数は数える。増え続けているなら UI が古い。 */
  unhandledFrames: number

  /** dev レイアウトの初期値は追従 OFF・map 固定（計画書 Phase 3）。 */
  followRobot: boolean
  headingUp: boolean

  setConnection: (state: ConnectionState, detail?: string) => void
  ingest: (frame: Record<string, unknown>, now?: number) => void
  setFollowRobot: (value: boolean) => void
  setHeadingUp: (value: boolean) => void
  clearError: () => void
  reset: () => void
}

export const useConsoleStore = create<ConsoleState>((set) => ({
  ...emptyFrameState(),
  connection: 'disconnected',
  connectionDetail: '',
  unhandledFrames: 0,
  followRobot: false,
  headingUp: false,

  setConnection: (connection, detail = '') =>
    set({ connection, connectionDetail: detail }),

  ingest: (frame, now = Date.now()) =>
    set((state) => {
      const { state: next, handled } = applyFrame(state, frame, now)
      return {
        ...next,
        unhandledFrames: handled ? state.unhandledFrames : state.unhandledFrames + 1,
      }
    }),

  setFollowRobot: (followRobot) => set({ followRobot }),
  setHeadingUp: (headingUp) => set({ headingUp }),
  clearError: () => set({ lastError: null }),

  // 再接続時に古い costmap を引きずらない。前の接続の地図に新しい
  // 部分更新を貼ると壊れた絵になる。
  reset: () => set({ ...emptyFrameState(), unhandledFrames: 0 }),
}))

export { isStale }
