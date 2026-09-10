import { formatDuration, formatRate } from '../lib/format'
import { useConsoleStore } from '../state/store'

/** bag 再生の位置と速度。**replay モードでのみ出る。**
 *
 * 出す理由は、止まっている絵が「再生が終わった」のか「その時刻に車体が
 * 止まっていた」のか区別できないため。代表 bag（2026-07-31）には実際に
 * 停止している区間があるので、これは実害のある曖昧さだった。
 *
 * ## シークは無い
 *
 * 任意の時刻へ飛ぶ機能は作らない。時刻が巻き戻ると costmap の seq 判定と
 * 「古さ」の判定が壊れる（`--loop` を使わないのと同じ理由。ADR-0004）。
 * 特定の時刻を見たいときは Foxglove を使う（設計原則 2）。
 */

/** 選べる再生速度。gateway 側の範囲 (0.1〜10) の中の実用的な点だけ出す。
 *
 * 任意の数値を入れさせない。刻んだところで見えるものは変わらず、
 * 入力欄が 1 つ増えるだけになる。 */
const RATES = [0.5, 1, 2, 4]

export interface ReplayBarProps {
  send: (frame: Record<string, unknown>) => boolean
}

export function ReplayBar({ send }: ReplayBarProps) {
  const replay = useConsoleStore((s) => s.replay)
  const connection = useConsoleStore((s) => s.connection)

  // gateway は replay モードでしか送ってこない。ここで mode を見ないのは、
  // status より replay フレームが先に届くことがあるため。
  if (replay === null) return null

  const connected = connection === 'connected'
  const { elapsed, total, rate, playing, finished } = replay
  const ratio =
    elapsed !== null && total !== null && total > 0
      ? Math.min(1, elapsed / total)
      : null

  const stateLabel = playing ? '再生中' : finished ? '再生終了' : '停止中'
  const stateClass = playing ? 'state-ok' : finished ? 'state-done' : 'state-down'

  return (
    <div className="replaybar" data-testid="replaybar">
      <span className={`badge ${stateClass}`} data-testid="replay-state">
        {stateLabel}
      </span>

      <span className="replay-clock" data-testid="replay-position">
        {formatDuration(elapsed)} / {formatDuration(total)}
      </span>

      {/* 全体長が分からないとき（metadata.yaml を読めなかった）は
          バーを出さない。0 % で描くと「先頭に居る」と誤読する。 */}
      {ratio === null ? (
        <span className="replay-nototal" data-testid="replay-no-total">
          全体長が不明（metadata.yaml を読めていない）
        </span>
      ) : (
        <span className="replay-track" data-testid="replay-track">
          <span
            className="replay-fill"
            data-testid="replay-fill"
            style={{ width: `${(ratio * 100).toFixed(1)}%` }}
          />
        </span>
      )}

      {/* 観測値であることを出す。指令 1.0 でも実機PC が重ければ遅れる。 */}
      <span className="badge" data-testid="replay-rate" title="実測（指令値ではない）">
        {formatRate(rate)}
      </span>

      <button
        type="button"
        data-testid="replay-toggle"
        // 終わった再生は再開できない。押せてしまうと「効かないボタン」になる。
        disabled={!connected || finished}
        title={finished ? '再生は終了している。見直すには起動し直すこと' : ''}
        onClick={() => send({ type: 'replay_control', action: playing ? 'pause' : 'resume' })}
      >
        {playing ? '一時停止' : '再開'}
      </button>

      <span className="replay-rates">
        {RATES.map((value) => (
          <button
            key={value}
            type="button"
            data-testid={`replay-rate-${value}`}
            disabled={!connected || finished}
            onClick={() => send({ type: 'replay_control', action: 'set_rate', rate: value })}
          >
            {value}x
          </button>
        ))}
      </span>

      {replay.bag && (
        <span className="replay-bag" data-testid="replay-bag" title={replay.bag}>
          {replay.bag.split('/').filter(Boolean).slice(-1)[0]}
        </span>
      )}
    </div>
  )
}
