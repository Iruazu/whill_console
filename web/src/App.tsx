import { useCallback, useState } from 'react'

import { useGateway } from './hooks/useGateway'
import { useStackd } from './hooks/useStackd'
import { useStoreProbe } from './hooks/useStoreProbe'
import { LAYOUT_DEFAULTS } from './lib/layout'
import { clearToken, loadToken } from './lib/token'
import { Overview2D } from './panels/Overview2D'
import { defaultStreams, streamsWithImage } from './lib/streams'
import { CameraPanel } from './panels/CameraPanel'
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
  /** 直前に gateway が返した拒否の理由。入力画面に出す（#58）。 */
  const [rejected, setRejected] = useState<string | null>(null)

  // 拒否されたトークンは保存から消して入力に戻す。残すと開き直しても同じ
  // トークンで拒否され続け、画面から抜け出せない（iPad で実際に詰まった）。
  const onAuthRejected = useCallback((reason: string) => {
    clearToken()
    setRejected(reason)
    setToken('')
  }, [])

  // この端末からトークンを消す。共有端末で使い終わったときと、
  // gateway のトークンを作り直したとき用。
  const forgetToken = useCallback(() => {
    clearToken()
    setRejected(null)
    setToken('')
  }, [])

  const client = useGateway(token, onAuthRejected)
  useStoreProbe()
  const stackd = useStackd(token)
  const layout = useConsoleStore((s) => s.layout)

  // 未接続のときは false を返す。押した感触だけあって何も起きない、を避ける。
  const send = useCallback(
    (frame: Record<string, unknown>) => client?.send(frame) ?? false,
    [client],
  )

  // 画像の購読を足し外しする。gateway は一覧で置き換えるので、既定の一覧を
  // 送り直す（lib/streams.ts）。
  const setImageSubscribed = useCallback(
    (on: boolean) => client?.subscribe(on ? streamsWithImage() : defaultStreams()),
    [client],
  )

  if (!token) {
    return (
      <TokenGate
        rejected={rejected}
        onSubmit={(next) => {
          setRejected(null)
          setToken(next)
        }}
      />
    )
  }

  const shows = LAYOUT_DEFAULTS[layout]

  return (
    <div className={`app layout-${layout}`}>
      <TopBar send={send} stackd={stackd} onForgetToken={forgetToken} />
      {/* replay モードでのみ描かれる（gateway が他モードでは送らない）。 */}
      <ReplayBar send={send} />
      <div className="layout">
        <Overview2D send={send} />
        <div className="side">
          {/* dispatch_node が居るモードでのみ描かれる。 */}
          {shows.showDispatch && <DispatchPanel send={send} />}
          {/* telemetry 宣言があるモードでのみ描かれる。 */}
          <DriversPanel />
          {shows.showCamera && <CameraPanel setImageSubscribed={setImageSubscribed} />}
          {/* 現場で 47 本のスライダーは要らない。触れてしまうほうが危ない。 */}
          {shows.showParams && <ParamsPanel send={send} />}
        </div>
      </div>
    </div>
  )
}
