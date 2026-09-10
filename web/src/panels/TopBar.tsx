import { useConsoleStore } from '../state/store'

/** 上部帯: 個体名 / real-sim-mock / 走行モード / 遅延 / スタック状態 / E-stop。
 *
 * E-stop は常に画面上にあること。安全は実機PC内で完結する（通信が切れても
 * 車体は止まる）が、操作者が押せる場所に無いと運用上は無いのと同じ。
 */
export function TopBar() {
  const connection = useConsoleStore((s) => s.connection)
  const detail = useConsoleStore((s) => s.connectionDetail)
  const status = useConsoleStore((s) => s.status)

  const mode = status?.mode ?? 'mock'
  const connected = connection === 'connected'
  // 繋がらない理由を隠さない。「gateway 未接続」だけだと、トークンが違うのか
  // gateway が落ちているのか区別できない。
  const label = connected
    ? 'gateway 接続'
    : detail
      ? `gateway ${connection}: ${detail}`
      : `gateway ${connection}`

  return (
    <div className="topbar" data-testid="topbar">
      <span className="robot">{status?.robotId ?? 'cr2-01'}</span>
      <span className={`badge mode-${mode}`}>{mode}</span>
      <span
        className={`badge ${connected ? 'state-ok' : 'state-down'}`}
        data-testid="connection"
      >
        {label}
      </span>
      <span className="badge">
        遅延 {status?.latencyMs != null ? `${status.latencyMs} ms` : '—'}
      </span>
      <span className={`badge ${status?.navActive ? 'state-ok' : 'state-down'}`}>
        Nav2 {status?.navActive ? 'active' : 'inactive'}
      </span>
      <span className="spacer" />
      <button className="estop" type="button" data-testid="estop">
        E-STOP
      </button>
    </div>
  )
}
