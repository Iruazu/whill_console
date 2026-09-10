import { useCallback, useState } from 'react'

import { useGateway } from './hooks/useGateway'
import { useStackd } from './hooks/useStackd'
import { useStoreProbe } from './hooks/useStoreProbe'
import { loadToken } from './lib/token'
import { Overview2D } from './panels/Overview2D'
import { ParamsPanel } from './panels/ParamsPanel'
import { TokenGate } from './panels/TokenGate'
import { TopBar } from './panels/TopBar'

/** dev レイアウト。
 *
 * パネルの中身は #20（俯瞰図）と #21（パラメータ）で作り込む。
 * ここは接続の配線とレイアウトだけ。
 */
export function App() {
  const [token, setToken] = useState(loadToken)
  const client = useGateway(token)
  useStoreProbe()
  const stackd = useStackd(token)

  // 未接続のときは false を返す。押した感触だけあって何も起きない、を避ける。
  const send = useCallback(
    (frame: Record<string, unknown>) => client?.send(frame) ?? false,
    [client],
  )

  if (!token) {
    return <TokenGate onSubmit={setToken} />
  }

  return (
    <div className="app">
      <TopBar send={send} stackd={stackd} />
      <div className="layout">
        <Overview2D send={send} />
        <ParamsPanel send={send} />
      </div>
    </div>
  )
}
