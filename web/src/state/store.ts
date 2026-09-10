import { create } from 'zustand'

import type {
  ConnectionState,
  CostmapFrame,
  ParamSpec,
  PathFrame,
  PoseFrame,
  StackStatus,
} from '../lib/types'

interface ConsoleState {
  connection: ConnectionState
  status: StackStatus | null
  costmap: CostmapFrame | null
  pose: PoseFrame | null
  path: PathFrame | null
  params: ParamSpec[]
  /** dev レイアウトの初期値は追従 OFF・map 固定（計画書 Phase 3）。 */
  followRobot: boolean
  headingUp: boolean

  setConnection: (state: ConnectionState) => void
  setStatus: (status: StackStatus) => void
  setCostmap: (frame: CostmapFrame) => void
  setPose: (frame: PoseFrame) => void
  setPath: (frame: PathFrame) => void
  setParams: (params: ParamSpec[]) => void
  setFollowRobot: (value: boolean) => void
  setHeadingUp: (value: boolean) => void
}

export const useConsoleStore = create<ConsoleState>((set) => ({
  connection: 'disconnected',
  status: null,
  costmap: null,
  pose: null,
  path: null,
  params: [],
  followRobot: false,
  headingUp: false,

  setConnection: (connection) => set({ connection }),
  setStatus: (status) => set({ status }),
  setCostmap: (costmap) => set({ costmap }),
  setPose: (pose) => set({ pose }),
  setPath: (path) => set({ path }),
  setParams: (params) => set({ params }),
  setFollowRobot: (followRobot) => set({ followRobot }),
  setHeadingUp: (headingUp) => set({ headingUp }),
}))
