import { useConsoleStore } from '../state/store'

/** 配車。既存 `whill_dispatch` の機能を gateway 経由で操作する。
 *
 * ブラウザは rosbridge を使わない。**開く WebSocket は gateway の 1 本だけ**
 * （設計原則 1）。gateway が `/dispatch/*` の内側に立って橋渡ししている。
 *
 * ## 手動操作はここに無い
 *
 * 既存 UI にある `/dispatch/teleop` は移植していない。gateway の手動操作
 * （`manual_vel` + ハートビート）と役割が同じで、両方生かすと
 * `/cmd_vel_teleop` に 2 経路から書き込むことになり、**どちらが止めているのか
 * 分からなくなる**（設計原則 4）。
 */

/** 終端の phase。次の job が始まるまで表示に残す。
 *
 * 消すのを急ぐと、短い job の結末を見逃す（`whill_dispatch` 側も同じ方針）。 */
const TERMINAL = new Set(['SUCCEEDED', 'ABORTED', 'CANCELED'])

const PHASE_LABEL: Record<string, string> = {
  IDLE: '待機中',
  QUEUED: '順番待ち',
  ACTIVE: '走行中',
  SUCCEEDED: '到着',
  ABORTED: '中断',
  CANCELED: '取り消し',
}

/** localization の fitness の警戒線。既存 UI（failsafe と同じ 1.0）に揃える。
 *
 * ずらすと「Web では緑なのに failsafe は止める」という食い違いができる。 */
const FITNESS_WARN = 1.0

export interface DispatchPanelProps {
  send: (frame: Record<string, unknown>) => boolean
}

export function DispatchPanel({ send }: DispatchPanelProps) {
  const dispatch = useConsoleStore((s) => s.dispatch)
  const waypoints = useConsoleStore((s) => s.waypoints)
  const connection = useConsoleStore((s) => s.connection)
  const estop = useConsoleStore((s) => s.status?.estop === true)

  // gateway は dispatch_node が居ないモードでは 1 通も送らない。
  // 空のパネルを出すと「配車できない」と「配車していない」が区別できない。
  if (dispatch === null) return null

  const connected = connection === 'connected'
  const phase = dispatch.phase ?? 'IDLE'
  const running = phase === 'ACTIVE' || phase === 'QUEUED'
  const terminal = TERMINAL.has(phase)

  return (
    <section className="panel dispatch" data-testid="dispatch">
      <header>
        <h2>配車</h2>
        <span
          className={`badge phase-${phase.toLowerCase()}`}
          data-testid="dispatch-phase"
        >
          {PHASE_LABEL[phase] ?? phase}
        </span>
        {dispatch.queueLen ? (
          <span className="badge" data-testid="dispatch-queue">
            待ち {dispatch.queueLen}
          </span>
        ) : null}
      </header>

      {/* 走行中の目的地と進捗。走っていないときは出さない —
          「進捗 0 %」と「まだ走っていない」を同じ絵にしない。 */}
      {(running || terminal) && dispatch.waypoint && (
        <div className="dispatch-active" data-testid="dispatch-active">
          <span className="dispatch-target">{dispatch.waypoint}</span>
          {dispatch.progress !== null && (
            <span className="progress-track" data-testid="dispatch-progress">
              <span
                className="progress-fill"
                style={{ width: `${Math.min(100, dispatch.progress * 100).toFixed(1)}%` }}
              />
            </span>
          )}
        </div>
      )}

      {/* 自己位置が合っているか。**配車してよいかの判断材料なので、
          行き先ボタンと同じ場所に出す。** 別のパネルに置くと見ないまま押す。 */}
      <div className="dispatch-health" data-testid="dispatch-health">
        <span
          className={`badge ${
            dispatch.aligned === null
              ? ''
              : dispatch.aligned
                ? 'state-ok'
                : 'state-down'
          }`}
          data-testid="dispatch-aligned"
        >
          自己位置 {dispatch.aligned === null ? '—' : dispatch.aligned ? 'OK' : 'NG'}
        </span>
        <span
          className={`badge ${
            dispatch.fitness === null
              ? ''
              : dispatch.fitness > FITNESS_WARN
                ? 'state-down'
                : 'state-ok'
          }`}
          data-testid="dispatch-fitness"
          title="scan-to-map の fitness（小さいほど良い）"
        >
          fitness {dispatch.fitness === null ? '—' : dispatch.fitness.toFixed(3)}
        </span>
      </div>

      {waypoints.length === 0 ? (
        <p className="muted" data-testid="dispatch-no-waypoints">
          地点が 1 つも無い。dispatch_node に渡した waypoints.yaml を確認すること。
        </p>
      ) : (
        <div className="dispatch-targets">
          {waypoints.map((wp) => (
            <button
              key={wp.name}
              type="button"
              data-testid={`dispatch-to-${wp.name}`}
              // E-stop 中は押せないと分かること。押した感触だけあって
              // 何も起きないのが最悪（上部帯の E-stop と同じ扱い）。
              disabled={!connected || estop}
              title={estop ? 'E-stop 作動中は配車できない' : ''}
              onClick={() => send({ type: 'dispatch_submit', waypoint: wp.name })}
            >
              {wp.label}
            </button>
          ))}
        </div>
      )}

      <button
        type="button"
        className="danger"
        data-testid="dispatch-cancel"
        // 走っていないものは取り消せない。
        disabled={!connected || !running}
        onClick={() => send({ type: 'dispatch_cancel' })}
      >
        取り消し
      </button>
    </section>
  )
}
