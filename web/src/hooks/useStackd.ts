import { useEffect, useState } from 'react'

import { socketUrl } from '../lib/gateway'

/** stackd（ポート 8770）の状態を読むだけの接続。
 *
 * gateway とは**別プロセス・別ポート**。stackd は gateway を含むスタック全体を
 * 起動・停止する側なので、同じプロセスには入れられない。
 *
 * ここでは読み取りだけ。起動・停止の操作は `whill stack` から行う
 * （画面から誤ってスタックを落とせるようにするのは、まだ早い）。
 *
 * stackd が動いていないのは異常ではない（`whill run` を手で叩く運用もある）。
 * 繋がらないことを騒がず、「未接続」とだけ出す。
 */

export interface StackdStatus {
  state: string
  pid: number | null
  exitCode: number | null
  uptime: number | null
}

const RETRY_MS = 15_000
/** 再接続の間隔。stackd は常駐しないこともあるので、gateway より緩くする。 */

export function useStackd(token: string, enabled = true): StackdStatus | null {
  const [status, setStatus] = useState<StackdStatus | null>(null)

  useEffect(() => {
    if (!token || !enabled) return
    let socket: WebSocket | null = null
    let timer: number | null = null
    let stopped = false

    const connect = () => {
      if (stopped) return
      // ページが https なら wss。gateway と同じ規則（lib/gateway.ts）。
      socket = new WebSocket(socketUrl(8770))

      socket.onopen = () => socket?.send(JSON.stringify({ type: 'auth', token }))
      socket.onmessage = (event) => {
        try {
          const frame = JSON.parse(String(event.data))
          if (frame.type === 'status') {
            setStatus({
              state: String(frame.state ?? 'unknown'),
              pid: typeof frame.pid === 'number' ? frame.pid : null,
              exitCode: typeof frame.exit_code === 'number' ? frame.exit_code : null,
              uptime: typeof frame.uptime === 'number' ? frame.uptime : null,
            })
          }
        } catch {
          // 壊れたフレームで接続を捨てない
        }
      }
      socket.onclose = () => {
        setStatus(null)
        if (!stopped) timer = window.setTimeout(connect, RETRY_MS)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      stopped = true
      if (timer !== null) window.clearTimeout(timer)
      socket?.close()
    }
  }, [token, enabled])

  return status
}
