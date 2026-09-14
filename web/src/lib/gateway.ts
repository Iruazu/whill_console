import type { ConnectionState } from './types'

/** gateway への WebSocket クライアント。
 *
 * ## 認証
 *
 * トークンは**最初のフレーム**で送る。クエリ文字列に載せない — URL は
 * ブラウザ履歴・プロキシログ・Referer に残る。gateway 側も最初のフレームが
 * `auth` でなければ切る作りになっている。
 *
 * ## 再接続
 *
 * 指数バックオフで繋ぎ直す。実機PC の再起動や Wi-Fi の瞬断で、画面を
 * 開き直さないと復帰しないのは運用上つらい。
 *
 * ただし**認証に失敗したときは再試行しない**。トークンが違うまま毎秒
 * 叩き続けても直らず、原因（トークンが違う）が画面から消えるだけ。
 */

export const RECONNECT_BASE_MS = 500
export const RECONNECT_MAX_MS = 10_000

export const PING_INTERVAL_MS = 2000
/** 遅延計測の周期。
 *
 * 往復で測る。`status` の `stamp` と受信時刻の差では測らない — ROS の時刻と
 * ブラウザの時計は同期していないし、replay モードでは `use_sim_time` で
 * ROS 側が実時刻ですらない。**往復なら時計合わせが要らない。**
 */

export interface GatewayOptions {
  url: string
  token: string
  /** 購読するストリーム。省略すると gateway の既定。 */
  streams?: string[]
  onState: (state: ConnectionState, detail?: string) => void
  onFrame: (frame: Record<string, unknown>) => void
  /** 往復遅延 (ms)。測れたときだけ呼ばれる。 */
  onLatency?: (ms: number) => void
  /** テスト用の差し替え口。既定はブラウザの WebSocket。 */
  socketFactory?: (url: string) => WebSocketLike
  /** 再接続の予約。テスト用の差し替え口。既定は setTimeout。 */
  schedule?: (fn: () => void, ms: number) => unknown
  cancel?: (handle: unknown) => void
  /** ping の周期実行。**再接続の予約とは別に持つ。**
   *  兼用すると、テストで再接続を進めたつもりが ping も撃つ、という
   *  紛らわしい状態になる。既定は setInterval。 */
  startInterval?: (fn: () => void, ms: number) => unknown
  stopInterval?: (handle: unknown) => void
}

/** 使う機能だけに絞ったインタフェース。テストで偽物を差せるようにするため。 */
export interface WebSocketLike {
  send(data: string): void
  close(): void
  onopen: ((event?: unknown) => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  onerror: ((event?: unknown) => void) | null
  onclose: ((event?: unknown) => void) | null
}

export class GatewayClient {
  private socket: WebSocketLike | null = null
  private attempt = 0
  private timer: unknown = null
  private closedByUs = false
  private authFailed = false
  private authenticated = false
  private pingTimer: unknown = null
  private pendingPing: { token: number; sentAt: number } | null = null
  private pingCounter = 0

  constructor(private readonly options: GatewayOptions) {}

  get isAuthenticated(): boolean {
    return this.authenticated
  }

  connect(): void {
    this.closedByUs = false
    this.authFailed = false
    this.open()
  }

  private open(): void {
    this.authenticated = false
    this.options.onState('connecting')

    const factory =
      this.options.socketFactory ?? ((url: string) => new WebSocket(url) as WebSocketLike)
    let socket: WebSocketLike
    try {
      socket = factory(this.options.url)
    } catch (error) {
      this.options.onState('error', (error as Error).message)
      this.scheduleReconnect()
      return
    }
    this.socket = socket

    socket.onopen = () => {
      // 認証が先。gateway は認証前に何も流さない。
      socket.send(JSON.stringify({ type: 'auth', token: this.options.token }))
      if (this.options.streams) {
        socket.send(
          JSON.stringify({ type: 'subscribe', streams: this.options.streams }),
        )
      }
    }

    socket.onmessage = (event) => {
      let frame: Record<string, unknown>
      try {
        frame = JSON.parse(String(event.data))
      } catch {
        // 壊れたフレーム 1 通で接続を捨てない。gateway 側のバグを
        // 再接続ループに変換すると、かえって切り分けが難しくなる。
        return
      }

      if (frame.type === 'hello' && frame.authenticated === true) {
        this.authenticated = true
        this.attempt = 0
        this.options.onState('connected')
        this.startPinging()
      }

      if (frame.type === 'pong') {
        const pending = this.pendingPing
        if (pending && frame.token === pending.token) {
          this.pendingPing = null
          this.options.onLatency?.(Date.now() - pending.sentAt)
        }
        return
      }

      if (frame.type === 'error' && frame.fatal === true) {
        // 認証拒否など、繋ぎ直しても直らないもの。理由を残して諦める。
        this.authFailed = true
        this.options.onState('error', String(frame.reason ?? '拒否された'))
      }

      this.options.onFrame(frame)
    }

    socket.onerror = () => {
      // onclose も続けて来るので、ここでは状態だけ。
      if (!this.authenticated) this.options.onState('error', '接続できない')
    }

    socket.onclose = () => {
      this.socket = null
      this.authenticated = false
      this.stopPinging()
      if (this.closedByUs) {
        this.options.onState('disconnected')
        return
      }
      if (this.authFailed) {
        // 再試行しない。トークンが違うまま叩き続けても直らない。
        this.options.onState('error', '認証に失敗した。トークンを確認すること')
        return
      }
      this.options.onState('disconnected')
      this.scheduleReconnect()
    }
  }

  private startPinging(): void {
    this.stopPinging()
    const start =
      this.options.startInterval ?? ((fn, ms) => setInterval(fn, ms))
    this.pingTimer = start(() => this.sendPing(), PING_INTERVAL_MS)
    this.sendPing()
  }

  private sendPing(): void {
    if (!this.socket || !this.authenticated) return
    this.pingCounter += 1
    this.pendingPing = { token: this.pingCounter, sentAt: Date.now() }
    this.socket.send(JSON.stringify({ type: 'ping', token: this.pingCounter }))
  }

  private stopPinging(): void {
    this.pendingPing = null
    if (this.pingTimer === null) return
    const stop =
      this.options.stopInterval ?? ((handle) => clearInterval(handle as number))
    stop(this.pingTimer)
    this.pingTimer = null
  }

  private scheduleReconnect(): void {
    if (this.closedByUs || this.authFailed) return
    const delay = backoffDelay(this.attempt)
    this.attempt += 1
    const schedule = this.options.schedule ?? ((fn, ms) => setTimeout(fn, ms))
    this.timer = schedule(() => this.open(), delay)
  }

  /** 購読を変える。gateway は購読変更のたびに現在の状態を配り直す。 */
  subscribe(streams: string[]): void {
    this.socket?.send(JSON.stringify({ type: 'subscribe', streams }))
  }

  send(frame: Record<string, unknown>): boolean {
    if (!this.socket || !this.authenticated) return false
    this.socket.send(JSON.stringify(frame))
    return true
  }

  close(): void {
    this.closedByUs = true
    this.stopPinging()
    const cancel = this.options.cancel ?? ((handle) => clearTimeout(handle as number))
    if (this.timer !== null) cancel(this.timer)
    this.timer = null
    this.socket?.close()
    this.socket = null
    this.authenticated = false
  }
}

/** 指数バックオフ。上限で頭打ちにする。 */
export function backoffDelay(attempt: number): number {
  return Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS)
}

/** ページの scheme に合わせた WebSocket の scheme（#55）。
 *
 * **https のページからは平文の `ws://` に繋げない**（混在コンテンツとして
 * ブラウザが拒否する）。iPad は http を https に上げてしまうので、iPad から
 * 使うときは必ず https + wss になる。
 */
export function socketScheme(pageProtocol: string): 'ws' | 'wss' {
  return pageProtocol === 'https:' ? 'wss' : 'ws'
}

/** いま開いているホストの、指定ポートの WebSocket URL。
 *
 * localhost 固定にすると、実機PC のサーバを他PC や tablet から開いたときに
 * 繋がらない。 */
export function socketUrl(
  port: number,
  location: Pick<Location, 'protocol' | 'hostname'> = window.location,
): string {
  const host = location.hostname || '127.0.0.1'
  return `${socketScheme(location.protocol)}://${host}:${port}`
}

/** 既定の接続先。いま開いているホストの 8765。 */
export function gatewayUrl(): string {
  return socketUrl(8765)
}
