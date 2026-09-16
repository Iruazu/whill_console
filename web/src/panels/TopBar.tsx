import { useState } from 'react'

import { formatLatency } from '../lib/format'
import type { StackdStatus } from '../hooks/useStackd'
import type { NavState } from '../lib/types'
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
  /** この端末からトークンを消して入力画面に戻す（#58）。 */
  onForgetToken?: () => void
}

/** Nav2 の状態の見せ方（#67）。
 *
 * **「active でない」を全部同じ赤にしない。** replay は Nav2 を上げないので
 * 赤くする理由が無く、起動直後の数秒も故障ではない。区別しないと、いつも
 * 赤い表示になって誰も見なくなる。
 *
 * 色だけで伝えない（屋外のタブレットで輝度と角度に負ける。色覚の差もある）ので、
 * 文字も状態ごとに変える。
 */
const NAV_LABEL: Record<NavState, string> = {
  active: '動作中',
  inactive: '停止中',
  down: '応答なし',
  starting: '起動中',
  not_started: '起動しない',
}

const NAV_BADGE: Record<NavState, string> = {
  active: 'state-ok',
  inactive: 'state-warn',
  down: 'state-down',
  starting: 'state-warn',
  not_started: '',
}

const NAV_TITLE: Record<NavState, string> = {
  active: 'Nav2 一式が activate されている',
  inactive: 'Nav2 は居るが activate されていない',
  down: '起動しているはずなのに応答が無い',
  starting: '起動直後。まだ応答が無い',
  not_started: 'このモードは Nav2 を起動しない（replay）',
}

export function TopBar({ send, stackd, onForgetToken }: TopBarProps) {
  const connection = useConsoleStore((s) => s.connection)
  const detail = useConsoleStore((s) => s.connectionDetail)
  const latency = useConsoleStore((s) => s.latencyMs)
  const status = useConsoleStore((s) => s.status)
  const layout = useConsoleStore((s) => s.layout)
  const setLayout = useConsoleStore((s) => s.setLayout)
  const [confirmRelease, setConfirmRelease] = useState(false)
  const [confirmForget, setConfirmForget] = useState(false)

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
          className={`badge ${NAV_BADGE[status?.navState ?? 'starting']}`}
          data-testid="nav-active"
          title={NAV_TITLE[status?.navState ?? 'starting']}
        >
          Nav2 {NAV_LABEL[status?.navState ?? 'starting']}
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

        {/* **画面幅で勝手に切り替えない。** 見ている最中にレイアウトが
            入れ替わるのは操作の途中では危ないし、デスクトップで ops を
            確認できないと崩れに気づけない。初回だけ幅で決めて、あとは
            この操作が正（lib/layout.ts）。 */}
        {onForgetToken && (
          <button
            type="button"
            className="layout-toggle"
            data-testid="token-forget"
            title="この端末に保存したトークンを消して、入力画面に戻る"
            onClick={() => setConfirmForget(true)}
          >
            トークンを消す
          </button>
        )}

        <button
          type="button"
          className="layout-toggle"
          data-testid="layout-toggle"
          title={layout === 'dev' ? '運用向けの画面に切り替える' : '開発向けの画面に切り替える'}
          onClick={() => setLayout(layout === 'dev' ? 'ops' : 'dev')}
        >
          {layout === 'dev' ? 'ops へ' : 'dev へ'}
        </button>

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

      {confirmForget && (
        <div className="modal" data-testid="token-forget-dialog">
          <div className="modal-body">
            <h2>この端末のトークンを消す</h2>
            <p>
              消すと gateway との接続が切れ、<strong>この端末からは E-STOP も
              届かなくなる</strong>。走行中なら先に止めること。
            </p>
            <p>共有端末で使い終わったときや、gateway のトークンを作り直したときに使う。</p>
            <div className="modal-actions">
              <button type="button" onClick={() => setConfirmForget(false)}>
                やめる
              </button>
              <button
                type="button"
                className="danger"
                data-testid="token-forget-confirm"
                onClick={() => {
                  setConfirmForget(false)
                  onForgetToken?.()
                }}
              >
                消す
              </button>
            </div>
          </div>
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
