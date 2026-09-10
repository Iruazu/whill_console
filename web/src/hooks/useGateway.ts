import { useEffect, useRef, useState } from 'react'

import { GatewayClient, gatewayUrl } from '../lib/gateway'
import { useConsoleStore } from '../state/store'

/** gateway に繋いで、届いたフレームを store に流し込む。
 *
 * トークンが無いあいだは繋ぎに行かない。空トークンで叩いても gateway に
 * 拒否されるだけで、画面には「認証に失敗した」しか出ず、原因（未設定）が
 * 分かりにくい。
 */
export function useGateway(token: string): GatewayClient | null {
  const setConnection = useConsoleStore((s) => s.setConnection)
  const ingest = useConsoleStore((s) => s.ingest)
  const reset = useConsoleStore((s) => s.reset)
  const [client, setClient] = useState<GatewayClient | null>(null)
  const wasConnected = useRef(false)

  useEffect(() => {
    if (!token) {
      setConnection('disconnected', 'トークンが未設定')
      return
    }

    const instance = new GatewayClient({
      url: gatewayUrl(),
      token,
      onState: (state, detail) => {
        // 切れたら保持していた地図を捨てる。前の接続の costmap に
        // 新しい部分更新を貼ると壊れた絵になる。
        if (state === 'connected') {
          wasConnected.current = true
        } else if (wasConnected.current) {
          wasConnected.current = false
          reset()
        }
        setConnection(state, detail)
      },
      onFrame: (frame) => ingest(frame),
    })
    instance.connect()
    setClient(instance)

    return () => {
      instance.close()
      setClient(null)
    }
  }, [token, setConnection, ingest, reset])

  return client
}
