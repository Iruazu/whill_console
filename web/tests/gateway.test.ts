import { describe, expect, it } from 'vitest'

import {
  GatewayClient,
  RECONNECT_MAX_MS,
  backoffDelay,
  socketScheme,
  socketUrl,
} from '../src/lib/gateway'
import type { WebSocketLike } from '../src/lib/gateway'
import type { ConnectionState } from '../src/lib/types'

/** 再接続と認証の筋を、本物の WebSocket 抜きで確かめる。
 *
 * 見たいのは 2 点:
 *   - 認証に失敗したときに繋ぎ直し続けないこと（原因が画面から消える）
 *   - 切れたら繋ぎ直すこと（画面を開き直さないと復帰しないのは運用上つらい）
 */

class FakeSocket implements WebSocketLike {
  sent: string[] = []
  closed = false
  onopen: ((event?: unknown) => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onerror: ((event?: unknown) => void) | null = null
  onclose: ((event?: unknown) => void) | null = null

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closed = true
    this.onclose?.()
  }

  frames(): Record<string, unknown>[] {
    return this.sent.map((s) => JSON.parse(s))
  }

  deliver(frame: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

interface Harness {
  client: GatewayClient
  sockets: FakeSocket[]
  states: { state: ConnectionState; detail?: string }[]
  frames: Record<string, unknown>[]
  /** 予約された再接続を実行する。 */
  runPending(): number
  pending: { fn: () => void; ms: number }[]
}

function harness(streams?: string[]): Harness {
  const sockets: FakeSocket[] = []
  const states: Harness['states'] = []
  const frames: Record<string, unknown>[] = []
  const pending: Harness['pending'] = []

  const client = new GatewayClient({
    url: 'ws://test:8765',
    token: 'test-token-1234',
    streams,
    onState: (state, detail) => states.push({ state, detail }),
    onFrame: (frame) => frames.push(frame),
    socketFactory: () => {
      const socket = new FakeSocket()
      sockets.push(socket)
      return socket
    },
    schedule: (fn, ms) => {
      pending.push({ fn, ms })
      return pending.length - 1
    },
    cancel: () => undefined,
  })

  return {
    client,
    sockets,
    states,
    frames,
    pending,
    runPending() {
      const count = pending.length
      const queued = pending.splice(0, pending.length)
      for (const item of queued) item.fn()
      return count
    },
  }
}

function authenticate(socket: FakeSocket): void {
  socket.onopen?.()
  socket.deliver({ type: 'hello', protocol: 1, authenticated: false })
  socket.deliver({ type: 'hello', protocol: 1, authenticated: true })
}

// ---- 認証 -------------------------------------------------------------------

describe('認証', () => {
  it('最初のフレームで token を送る', () => {
    // クエリ文字列に載せない。URL は履歴・プロキシログに残る。
    const h = harness()
    h.client.connect()
    h.sockets[0].onopen?.()

    const first = h.sockets[0].frames()[0]
    expect(first.type).toBe('auth')
    expect(first.token).toBe('test-token-1234')
  })

  it('streams を指定すると subscribe も送る', () => {
    const h = harness(['costmap', 'pose'])
    h.client.connect()
    h.sockets[0].onopen?.()

    const kinds = h.sockets[0].frames().map((f) => f.type)
    expect(kinds).toEqual(['auth', 'subscribe'])
  })

  it('authenticated な hello で connected になる', () => {
    const h = harness()
    h.client.connect()
    authenticate(h.sockets[0])

    expect(h.states.map((s) => s.state)).toContain('connected')
    expect(h.client.isAuthenticated).toBe(true)
  })

  it('認証前は送信を拒否する', () => {
    const h = harness()
    h.client.connect()
    h.sockets[0].onopen?.()

    expect(h.client.send({ type: 'estop', engage: true })).toBe(false)
  })

  it('認証後は送信できる', () => {
    const h = harness()
    h.client.connect()
    authenticate(h.sockets[0])

    expect(h.client.send({ type: 'estop', engage: true })).toBe(true)
    expect(h.sockets[0].frames().at(-1)).toEqual({ type: 'estop', engage: true })
  })
})

// ---- 再接続 -----------------------------------------------------------------

describe('再接続', () => {
  it('切れたら繋ぎ直す', () => {
    const h = harness()
    h.client.connect()
    authenticate(h.sockets[0])

    h.sockets[0].onclose?.()
    expect(h.pending.length).toBe(1)
    h.runPending()
    expect(h.sockets.length).toBe(2)
  })

  it('繋がるたびに待ち時間がリセットされる', () => {
    const h = harness()
    h.client.connect()

    // 何度か失敗させて待ち時間を伸ばす
    h.sockets[0].onclose?.()
    h.runPending()
    h.sockets[1].onclose?.()
    const grown = h.pending[0].ms
    h.runPending()

    // 3 回目で繋がったら、次の切断は最短から
    authenticate(h.sockets[2])
    h.sockets[2].onclose?.()
    expect(h.pending[0].ms).toBeLessThan(grown)
  })

  it('認証に失敗したら繋ぎ直さない', () => {
    // トークンが違うまま毎秒叩いても直らず、原因が画面から消えるだけ
    const h = harness()
    h.client.connect()
    h.sockets[0].onopen?.()
    h.sockets[0].deliver({ type: 'error', reason: 'トークンが違う', fatal: true })
    h.sockets[0].onclose?.()

    expect(h.pending.length).toBe(0)
    const last = h.states.at(-1)!
    expect(last.state).toBe('error')
    expect(last.detail).toMatch(/トークン/)
  })

  it('こちらから閉じたら繋ぎ直さない', () => {
    const h = harness()
    h.client.connect()
    authenticate(h.sockets[0])

    h.client.close()
    expect(h.pending.length).toBe(0)
    expect(h.states.at(-1)?.state).toBe('disconnected')
  })

  it('接続自体が作れなくても諦めずに再試行する', () => {
    const states: { state: ConnectionState }[] = []
    const pending: (() => void)[] = []
    const client = new GatewayClient({
      url: 'ws://test:8765',
      token: 'test-token-1234',
      onState: (state) => states.push({ state }),
      onFrame: () => undefined,
      socketFactory: () => {
        throw new Error('だめ')
      },
      schedule: (fn) => {
        pending.push(fn)
        return pending.length
      },
      cancel: () => undefined,
    })
    client.connect()

    expect(states.at(-1)?.state).toBe('error')
    expect(pending.length).toBe(1)
  })
})

describe('バックオフ', () => {
  it('回を追うごとに伸びる', () => {
    expect(backoffDelay(1)).toBeGreaterThan(backoffDelay(0))
    expect(backoffDelay(3)).toBeGreaterThan(backoffDelay(2))
  })

  it('上限で頭打ちになる', () => {
    // 伸び続けると実機PC が戻ってきても何分も繋がらないことになる
    expect(backoffDelay(50)).toBe(RECONNECT_MAX_MS)
  })
})

// ---- フレームの受け渡し -----------------------------------------------------

describe('フレーム', () => {
  it('受け取ったフレームをそのまま渡す', () => {
    const h = harness()
    h.client.connect()
    authenticate(h.sockets[0])
    h.sockets[0].deliver({ type: 'pose', x: 1 })

    expect(h.frames.at(-1)).toEqual({ type: 'pose', x: 1 })
  })

  it('壊れた JSON で接続を捨てない', () => {
    // gateway 側のバグを再接続ループに変換すると切り分けが難しくなる
    const h = harness()
    h.client.connect()
    authenticate(h.sockets[0])
    h.sockets[0].onmessage?.({ data: '{{{' })

    expect(h.sockets[0].closed).toBe(false)
    expect(h.client.isAuthenticated).toBe(true)
  })
})

describe('WebSocket の scheme（#55）', () => {
  it('https のページからは wss で繋ぐ', () => {
    // https のページから平文の ws:// には繋げない（混在コンテンツ）。
    // iPad は http を https に上げるので、iPad から使うときは必ずこちら。
    expect(socketScheme('https:')).toBe('wss')
    expect(socketUrl(8765, { protocol: 'https:', hostname: '172.20.10.2' }))
      .toBe('wss://172.20.10.2:8765')
  })

  it('http のページからは ws で繋ぐ', () => {
    expect(socketScheme('http:')).toBe('ws')
    expect(socketUrl(8770, { protocol: 'http:', hostname: 'localhost' }))
      .toBe('ws://localhost:8770')
  })

  it('ホスト名が無ければ 127.0.0.1', () => {
    expect(socketUrl(8765, { protocol: 'http:', hostname: '' })).toBe('ws://127.0.0.1:8765')
  })
})
