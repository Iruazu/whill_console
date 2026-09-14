import { useEffect, useState } from 'react'

import { TF_EDGE_MARK, TF_HEALTH_MARK, buildTfTree, edgeDetail, tfHealth } from '../lib/tf'
import type { TfNode } from '../lib/tf'
import { LAYOUT_DEFAULTS } from '../lib/layout'
import { useConsoleStore } from '../state/store'

/** tf パネル（#51）。
 *
 * ## 繋がりだけでなく、止まったかを出す
 *
 * TF の途絶は Nav2 が止まる一番多い原因で、止まっても親子関係は変わらない。
 * 木の絵だけでは健全なときと区別できないので、辺ごとの古さと実測レートを添える。
 *
 * ## ops では異常のときだけ一行
 *
 * 運用中に木を眺めることは無い。問題があるときだけ、何が止まっているかを出す。
 *
 * 変換の数値（位置・姿勢）は出さない（設計原則 2。Foxglove に委譲する）。
 */

/** tf 要約はこれだけ来なければ古い。gateway は 1 Hz で送る。 */
export const TF_FRAME_STALE_MS = 3000

export function TfPanel() {
  const tf = useConsoleStore((s) => s.tf)
  const receivedAt = useConsoleStore((s) => s.receivedAt.tf)
  const layout = useConsoleStore((s) => s.layout)
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  if (tf === null) return null

  const health = tfHealth(tf)
  // 要約そのものが止まったら、中身の OK を信じない（gateway が止まっている）。
  const frameStale = receivedAt !== undefined && now - receivedAt > TF_FRAME_STALE_MS

  if (!LAYOUT_DEFAULTS[layout].showTfTree) {
    if (health.level === 'ok' || frameStale) return null
    return (
      <section className={`panel tf ops level-${health.level}`} data-testid="tf-alert">
        <span className={`badge level-${health.level}`}>TF {TF_HEALTH_MARK[health.level]}</span>
        <span>{health.reasons[0]}</span>
      </section>
    )
  }

  const level = frameStale ? 'stale' : health.level
  const mark = frameStale ? '古' : TF_HEALTH_MARK[health.level]
  const trees = buildTfTree(tf)

  return (
    <section className="panel tf" data-testid="tf">
      <button
        type="button"
        className="camera-toggle"
        aria-expanded={open}
        data-testid="tf-toggle"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="driver-caret">{open ? '▾' : '▸'}</span>
        <h2>TF</h2>
        <span className={`badge level-${level}`} data-testid="tf-level">
          {mark}
        </span>
        <span className="muted">
          辺 {tf.edges.length}
          {tf.missing.length > 0 && ` / 無い ${tf.missing.length}`}
        </span>
      </button>

      {/* 畳んでいても理由は出す。隠れていると開く理由に気づけない。 */}
      {health.reasons.length > 0 && (
        <ul className="tf-reasons" data-testid="tf-reasons">
          {health.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {frameStale && (
        <p className="muted" data-testid="tf-stale">
          tf の要約が届いていない。gateway との接続を確認すること。
        </p>
      )}

      {open && (
        <ul className="tf-tree" data-testid="tf-tree">
          {trees.map((node) => (
            <TfTreeNode key={node.frame} node={node} />
          ))}
        </ul>
      )}
    </section>
  )
}

function TfTreeNode({ node }: { node: TfNode }) {
  const edge = node.edge
  return (
    <li data-testid={`tf-frame-${node.frame}`}>
      <div className={`tf-row${edge ? ` level-${edge.level}` : ''}`}>
        <span className="tf-frame">{node.frame}</span>
        {edge && (
          <>
            <span className={`badge level-${edge.level}`}>{TF_EDGE_MARK[edge.level]}</span>
            <span className="muted">{edgeDetail(edge)}</span>
          </>
        )}
      </div>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((child) => (
            <TfTreeNode key={child.frame} node={child} />
          ))}
        </ul>
      )}
    </li>
  )
}
