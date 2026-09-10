import { useState } from 'react'

import { formatLatency } from '../lib/format'
import type { StackdStatus } from '../hooks/useStackd'
import { useConsoleStore } from '../state/store'

/** 上部帯: 個体名 / モード / 遅延 / スタック状態 / E-stop。
 *
 * いま何が起きているかを 1 行で分かるようにする。**繋がらない理由を隠さない。**
 * 「gateway 未接続」だけだと、トークンが違うのか gateway が落ちているのか
 * 区別できず、現地で切り分けができない。
 */

export interface TopBarProps {
  send: (frame: Record<string, unknown>) => boolean
  stackd: StackdStatus | null
}

export function TopBar({ send, stackd }: TopBarProps) {
  const connection = useConsoleStore((s) => s.connection)
  const detail = useConsoleStore((s) => s.connectionDetail)
  const latency = useConsoleStore((s) => s.latencyMs)
  const status = useConsoleStore((s) => s.status)
  const [confirmRelease, setConfirmRelease] = useState(false)

  const connected = connection === 'connected'
  const estop = status?.estop === true
  const mode = status?.mode ?? '—'

  const connectionLabel = connected
    ? 'gateway 接続'
    : detail
      ? `gateway ${connection}: ${detail}`
      : `gateway ${connection}`

  const onEstop = () => {
    if (estop) {
      setConfirmRelease(true)
      return
    }
    send({ type: 'estop', engage: true })
  }

  return (
    <>
      <div className={`topbar${estop ? ' estop-engaged' : ''}`} data-testid="topbar">
        <span className="robot">{status?.robotId ?? '—'}</span>
        <span className={`badge mode-${mode}`} data-testid="mode">
          {mode}
        </span>
        <span
          className={`badge ${connected ? 'state-ok' : 'state-down'}`}
          data-testid="connection"
        >
          {connectionLabel}
        </span>
        <span className="badge" data-testid="latency" title="gateway との往復">
          遅延 {formatLatency(latency)}
        </span>
        <span
          className={`badge ${status?.navActive ? 'state-ok' : 'state-down'}`}
          data-testid="nav-active"
        >
          Nav2 {status?.navActive ? 'active' : 'inactive'}
        </span>
        <span className="badge" data-testid="stackd">
          stackd{' '}
          {stackd === null
            ? '未接続'
            : stackd.exitCode !== null && stackd.state === 'failed'
              ? `failed (exit ${stackd.exitCode})`
              : stackd.state}
        </span>
        {status && status.clients > 1 && (
          <span className="badge" data-testid="clients">
            {status.clients} 人が接続中
          </span>
        )}

        <span className="spacer" />

        {/* 未接続なら押せないと分かること。押した感触だけあって何も起きないのが最悪。 */}
        <button
          className={`estop${estop ? ' engaged' : ''}`}
          type="button"
          data-testid="estop"
          disabled={!connected}
          title={connected ? '' : 'gateway に繋がっていないので届かない'}
          onClick={onEstop}
        >
          {estop ? 'E-STOP 解除' : 'E-STOP'}
        </button>
      </div>

      {estop && (
        <div className="estop-banner" data-testid="estop-banner">
          E-STOP 作動中。自律走行と手動操作を遮断している。
        </div>
      )}

      {confirmRelease && (
        <div className="modal" data-testid="estop-release-dialog">
          <div className="modal-body">
            <h2>E-STOP を解除する</h2>
            <p>
              解除は「止めるのをやめる」であって「再開する」ではない。
              gateway は E-stop 時に Nav2 の goal を取り消しているので、
              <strong>解除しても自律走行は再開しない</strong>。
              走らせるには改めてゴールを与えること。
            </p>
            <p>車体の周りが安全か確認したか。</p>
            <div className="modal-actions">
              <button type="button" onClick={() => setConfirmRelease(false)}>
                やめる
              </button>
              <button
                type="button"
                className="danger"
                data-testid="estop-release-confirm"
                onClick={() => {
                  send({ type: 'estop', engage: false })
                  setConfirmRelease(false)
                }}
              >
                解除する
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
