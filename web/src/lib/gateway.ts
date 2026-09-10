import type { ConnectionState } from './types'

/** gateway への WebSocket クライアント。
 *
 * 本体の実装は Phase 2。ここでは接続の骨格と、認証トークンの載せ方だけ
 * 決めておく。トークンはクエリ文字列ではなく最初のフレームで送る
 * （URL はブラウザ履歴やプロキシログに残るため）。
 */
export interface GatewayOptions {
  url: string
  token: string
  onState: (state: ConnectionState) => void
  onMessage: (message: unknown) => void
}

export class GatewayClient {
  private socket: WebSocket | null = null

  constructor(private readonly options: GatewayOptions) {}

  connect(): void {
    this.options.onState('connecting')
    const socket = new WebSocket(this.options.url)
    this.socket = socket

    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'auth', token: this.options.token }))
      this.options.onState('connected')
    }
    socket.onmessage = (event) => {
      try {
        this.options.onMessage(JSON.parse(event.data as string))
      } catch {
        // 壊れたフレームで接続ごと落とさない。gateway 側のバグを
        // UI の再接続ループに変換しても切り分けが難しくなるだけ。
      }
    }
    socket.onerror = () => this.options.onState('error')
    socket.onclose = () => this.options.onState('disconnected')
  }

  close(): void {
    this.socket?.close()
    this.socket = null
  }
}

export function gatewayUrl(): string {
  // 既定は「今開いているホストの 8765」。実機PC の dev サーバを他PC から
  // 開く運用なので、localhost 固定にすると他PC から繋がらない。
  const host = window.location.hostname || '127.0.0.1'
  return `ws://${host}:8765`
}
