import { useCallback, useState } from 'react'

import { useGateway } from './hooks/useGateway'
import { useStackd } from './hooks/useStackd'
import { useStoreProbe } from './hooks/useStoreProbe'
import { LAYOUT_DEFAULTS } from './lib/layout'
import { loadToken } from './lib/token'
import { Overview2D } from './panels/Overview2D'
import { DispatchPanel } from './panels/DispatchPanel'
import { DriversPanel } from './panels/DriversPanel'
import { ParamsPanel } from './panels/ParamsPanel'
import { ReplayBar } from './panels/ReplayBar'
import { TokenGate } from './panels/TokenGate'
import { TopBar } from './panels/TopBar'
import { useConsoleStore } from './state/store'

/** dev / ops の 2 レイアウト。
 *
 * 出すものが違うだけで、**データの経路は同じ。** ops 専用のストリームは
 * 作らない（#39〜#42 が配るものを並べ替えるだけ）。
 *
 * 何を出す / 出さないかは `lib/layout.ts` の `LAYOUT_DEFAULTS` が持つ。
 * ここに条件を散らさないこと。
 */
export function App() {
  const [token, setToken] = useState(loadToken)
  const client = useGateway(token)
  useStoreProbe()
  const stackd = useStackd(token)
  const layout = useConsoleStore((s) => s.layout)

  // 未接続のときは false を返す。押した感触だけあって何も起きない、を避ける。
  const send = useCallback(
    (frame: Record<string, unknown>) => client?.send(frame) ?? false,
    [client],
  )

  if (!token) {
    return <TokenGate onSubmit={setToken} />
  }

  const shows = LAYOUT_DEFAULTS[layout]

  return (
    <div className={`app layout-${layout}`}>
      <TopBar send={send} stackd={stackd} />
      {/* replay モードでのみ描かれる（gateway が他モードでは送らない）。 */}
      <ReplayBar send={send} />
      <div className="layout">
        <Overview2D send={send} />
        <div className="side">
          {/* dispatch_node が居るモードでのみ描かれる。 */}
          {shows.showDispatch && <DispatchPanel send={send} />}
          {/* telemetry 宣言があるモードでのみ描かれる。 */}
          <DriversPanel />
          {/* 現場で 47 本のスライダーは要らない。触れてしまうほうが危ない。 */}
          {shows.showParams && <ParamsPanel send={send} />}
        </div>
      </div>
    </div>
  )
}
