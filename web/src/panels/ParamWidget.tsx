import { useEffect, useState } from 'react'

import type { ParamSpec } from '../lib/types'

/** パラメータ 1 件のウィジェット。
 *
 * **一覧をハードコードしない。** 型・範囲・単位・説明は全部 gateway が
 * registry から配ってくるものを使う（設計原則 6、ADR-0001）。ここで
 * `if (key === 'desired_linear_vel')` のような分岐を書き始めたら負け。
 */

export interface ParamWidgetProps {
  spec: ParamSpec
  /** 走行中か。`locked_while_moving` を無効化する。 */
  moving: boolean
  /** gateway から結果が返るたびに増える。下書きを捨てる合図。 */
  revision: number
  onChange: (key: string, value: ParamSpec['value']) => void
}

export function ParamWidget({ spec, moving, revision, onChange }: ParamWidgetProps) {
  const lockedNow = spec.safetyClass === 'locked_while_moving' && moving
  // live: false は送っても gateway が拒否する。押せるように見せない。
  const disabled = !spec.live || lockedNow

  const reason = !spec.live
    ? '再起動が必要（live: false）'
    : lockedNow
      ? '走行中は変更できない（locked_while_moving）'
      : ''

  return (
    <div className="param" data-testid={`param-${spec.key}`} data-locked={lockedNow}>
      <div className="param-head">
        {/* 説明はここにしか無い。値の由来（なぜ 0.6 なのか）が読めること。 */}
        <span className="param-name" title={spec.description}>
          {spec.name}
        </span>
        <ParamBadges spec={spec} lockedNow={lockedNow} />
      </div>

      <ParamControl spec={spec} disabled={disabled} revision={revision} onChange={onChange} />

      {reason && <p className="param-reason">{reason}</p>}
    </div>
  )
}

function ParamBadges({ spec, lockedNow }: { spec: ParamSpec; lockedNow: boolean }) {
  return (
    <span className="param-badges">
      {spec.unit && <span className="badge unit">{spec.unit}</span>}
      <span className={`badge ${spec.live ? 'live' : 'restart'}`}>
        {spec.live ? 'live' : 'restart'}
      </span>
      {spec.safetyClass !== 'none' && (
        <span
          className={`badge safety-${spec.safetyClass}${lockedNow ? ' locked-now' : ''}`}
        >
          {spec.safetyClass === 'caution' ? 'caution' : 'locked'}
        </span>
      )}
    </span>
  )
}

function ParamControl({
  spec,
  disabled,
  revision,
  onChange,
}: {
  spec: ParamSpec
  disabled: boolean
  revision: number
  onChange: (key: string, value: ParamSpec['value']) => void
}) {
  if (spec.type === 'bool') {
    return (
      <label className="param-bool">
        <input
          type="checkbox"
          checked={spec.value === true}
          disabled={disabled}
          onChange={(e) => onChange(spec.key, e.target.checked)}
          data-testid={`input-${spec.key}`}
        />
        {String(spec.value)}
      </label>
    )
  }

  if (spec.type === 'string') {
    return (
      <TextControl spec={spec} disabled={disabled} onChange={onChange} />
    )
  }

  if (spec.type === 'double_array') {
    // 軸ごとに範囲が違う。差動二輪の vy は min=max=0 で動かせない。
    const values = Array.isArray(spec.value) ? spec.value : []
    return (
      <div className="param-axes">
        {(spec.elements ?? []).map((element, index) => (
          <NumberControl
            key={element.label}
            testId={`input-${spec.key}-${element.label}`}
            label={element.label}
            value={values[index] ?? 0}
            range={element.range}
            disabled={disabled}
            revision={revision}
            onCommit={(next) => {
              const updated = [...values]
              updated[index] = next
              onChange(spec.key, updated)
            }}
          />
        ))}
      </div>
    )
  }

  return (
    <NumberControl
      testId={`input-${spec.key}`}
      value={typeof spec.value === 'number' ? spec.value : 0}
      range={spec.range ?? undefined}
      integer={spec.type === 'int'}
      disabled={disabled}
      revision={revision}
      onCommit={(next) => onChange(spec.key, next)}
    />
  )
}

function TextControl({
  spec,
  disabled,
  onChange,
}: {
  spec: ParamSpec
  disabled: boolean
  onChange: (key: string, value: ParamSpec['value']) => void
}) {
  const [draft, setDraft] = useState(String(spec.value ?? ''))
  useEffect(() => setDraft(String(spec.value ?? '')), [spec.value])

  return (
    <input
      type="text"
      className="param-text"
      value={draft}
      disabled={disabled}
      data-testid={`input-${spec.key}`}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft !== spec.value && onChange(spec.key, draft)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onChange(spec.key, draft)
      }}
    />
  )
}

/** スライダー + 数値入力。
 *
 * スライダーだけだと細かい値を入れられず、数値入力だけだと「どのくらい
 * 動かせるのか」が分からない。両方出す。
 *
 * 送信はスライダーを離したとき（`onMouseUp` 相当の `onChange` 確定時）。
 * ドラッグ中に毎フレーム送ると、Nav2 に不要な set が殺到する。
 */
function NumberControl({
  value,
  range,
  integer = false,
  disabled,
  label,
  testId,
  revision,
  onCommit,
}: {
  value: number
  range?: { min?: number; max?: number; step?: number }
  integer?: boolean
  disabled: boolean
  label?: string
  testId: string
  revision: number
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(value)
  // revision も見る。拒否されたときは value が変わらないので、value だけを
  // 見ていると拒否された入力が欄に残り続ける（実際は 0.85 なのに 9.9 と
  // 表示される）。実機で踏んだ。
  useEffect(() => setDraft(value), [value, revision])

  const min = range?.min ?? 0
  const max = range?.max ?? 1
  const step = range?.step ?? (integer ? 1 : 0.01)
  // 差動二輪の vy のように動かせない軸がある。触れるように見せない。
  const fixed = min === max

  return (
    <div className="param-number">
      {label && <span className="axis-label">{label}</span>}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled || fixed}
        data-testid={`${testId}-range`}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={() => draft !== value && onCommit(draft)}
        onKeyUp={() => draft !== value && onCommit(draft)}
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled || fixed}
        data-testid={testId}
        onChange={(e) => setDraft(Number(e.target.value))}
        onBlur={() => draft !== value && onCommit(draft)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onCommit(draft)
        }}
      />
    </div>
  )
}
