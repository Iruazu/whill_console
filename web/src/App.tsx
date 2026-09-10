import { useState } from 'react'

import { useGateway } from './hooks/useGateway'
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
  useGateway(token)
  useStoreProbe()

  if (!token) {
    return <TokenGate onSubmit={setToken} />
  }

  return (
    <div className="app">
      <TopBar />
      <div className="layout">
        <Overview2D />
        <ParamsPanel />
      </div>
    </div>
  )
}
