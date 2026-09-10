import { useMemo, useState } from 'react'

import type { ParamSpec } from '../lib/types'
import { useConsoleStore } from '../state/store'
import { ParamWidget } from './ParamWidget'

/** パラメータ操作。
 *
 * 表示するものは gateway が registry から introspection して送ってくる。
 * **ここに一覧をハードコードしないこと**（設計原則 6）。
 *
 * 拒否の理由は必ず出す。黙って値が戻ると「動かしたのに変わらない」になり、
 * 範囲外なのか走行中なのか再起動が要るのか区別できない。
 */

export interface ParamsPanelProps {
  /** gateway へフレームを送る。未接続なら false を返す。 */
  send: (frame: Record<string, unknown>) => boolean
}

export function ParamsPanel({ send }: ParamsPanelProps) {
  const params = useConsoleStore((s) => s.params)
  const mismatches = useConsoleStore((s) => s.mismatches)
  const unreachable = useConsoleStore((s) => s.unreachable)
  const presets = useConsoleStore((s) => s.presets)
  const appliedPreset = useConsoleStore((s) => s.appliedPreset)
  const changes = useConsoleStore((s) => s.paramChanges)
  const revisions = useConsoleStore((s) => s.paramRevision)
  const status = useConsoleStore((s) => s.status)
  const [filter, setFilter] = useState('')
  const [liveOnly, setLiveOnly] = useState(false)

  // 走行中かどうかは gateway が status で配る nav_active では足りない
  // （手動操作でも動く）。gateway 側が最終判断をするので、UI は
  // 「無効化して見せる」だけにとどめる。
  const moving = status?.navActive === true

  const grouped = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const groups: Record<string, ParamSpec[]> = {}
    for (const spec of params) {
      if (liveOnly && !spec.live) continue
      if (needle && !spec.key.toLowerCase().includes(needle)) continue
      ;(groups[spec.node] ??= []).push(spec)
    }
    for (const list of Object.values(groups)) {
      list.sort((a, b) => a.name.localeCompare(b.name))
    }
    return groups
  }, [params, filter, liveOnly])

  const setValue = (key: string, value: ParamSpec['value']) => {
    if (!send({ type: 'param_set', key, value })) {
      // 送れなかったことを黙らない。押した感触だけあって何も起きないのが最悪。
      useConsoleStore.getState().ingest({
        type: 'param_changed', key, accepted: false,
        value: params.find((p) => p.key === key)?.value,
        reason: 'gateway に繋がっていない',
      })
    }
  }

  if (params.length === 0) {
    return (
      <div className="panel params" data-testid="params">
        <h2>パラメータ</h2>
        <p className="placeholder">
          registry 未受信。gateway に繋がると、ここにスライダーが自動生成される。
        </p>
      </div>
    )
  }

  return (
    <div className="panel params" data-testid="params">
      <h2>パラメータ（{params.length}）</h2>

      <div className="params-toolbar">
        <input
          type="search"
          placeholder="絞り込み"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          data-testid="params-filter"
        />
        <label>
          <input
            type="checkbox"
            checked={liveOnly}
            onChange={(e) => setLiveOnly(e.target.checked)}
            data-testid="params-live-only"
          />{' '}
          live のみ
        </label>
        <select
          value={appliedPreset ?? ''}
          onChange={(e) => e.target.value && send({ type: 'preset_apply', name: e.target.value })}
          data-testid="preset-select"
        >
          <option value="">preset を選ぶ</option>
          {presets.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      {unreachable.length > 0 && (
        <p className="notice warn" data-testid="unreachable">
          応答しないノード: {unreachable.join(', ')}
          <br />
          表示中の値は registry のもので、実際の値ではない。
        </p>
      )}

      {mismatches.length > 0 && (
        <div className="notice warn" data-testid="mismatches">
          <strong>registry と実ノードの値がずれている（{mismatches.length} 件）</strong>
          <ul>
            {mismatches.slice(0, 5).map((m) => (
              <li key={m.key}>
                {m.key}: registry {String(m.registry)} / 実際 {String(m.live)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {Object.entries(grouped)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([node, specs]) => (
          <section key={node} className="param-group">
            <h3>
              {node}
              <span className="ros-node">{specs[0].rosNode}</span>
            </h3>
            {specs.map((spec) => (
              <ParamWidget
                key={spec.key}
                spec={spec}
                moving={moving}
                revision={revisions[spec.key] ?? 0}
                onChange={setValue}
              />
            ))}
          </section>
        ))}

      <ChangeLog changes={changes} />
    </div>
  )
}

/** 変更ログ。**拒否も残す。**
 *
 * 受理だけ記録すると「UI で動かしたのに変わらなかった」原因が追えない。
 * gateway 側は `/whill/param_changes` にも publish していて MCAP に載る。
 */
function ChangeLog({ changes }: { changes: ReturnType<typeof useConsoleStore.getState>['paramChanges'] }) {
  if (changes.length === 0) return null
  return (
    <section className="param-group change-log" data-testid="change-log">
      <h3>変更ログ</h3>
      <ul>
        {changes.slice(0, 20).map((change, index) => (
          <li key={`${change.key}-${change.stamp}-${index}`}
              className={change.accepted ? 'ok' : 'ng'}>
            <span className="mark">{change.accepted ? 'OK' : 'NG'}</span>{' '}
            {change.key} = {String(change.value)}
            {!change.accepted && change.reason && (
              <span className="why"> — {change.reason}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
