import { useState } from 'react'

import {
  LEVEL_MARK,
  barRatio,
  formatAge,
  formatValue,
  isDown,
  isOffByDeclaration,
  summaryItems,
  worstLevel,
} from '../lib/telemetry'
import { LAYOUT_DEFAULTS, opsItems } from '../lib/layout'
import type { TelemetryDriver, TelemetryItem } from '../lib/types'
import { useConsoleStore } from '../state/store'

/** ドライバごとのテレメトリ。
 *
 * 閾値の判定は gateway が済ませてある（#39）。**ここでは `level` を色と文字に
 * 写すだけ。** UI 側で閾値を見直すと `whill doctor` や CLI と答えが食い違う。
 *
 * ## 時系列は出さない
 *
 * 設計原則 2。値の推移が見たいときは Foxglove / Lichtblick を使う。ここが
 * 見せるのは「いまの値」と「危ないかどうか」だけ。
 *
 * ## ops では主要テレメトリだけ
 *
 * 電流や温度は切り分けのための数字で、運用中に見るものではない。**どれを
 * 主要とするかは `config/robots/cr2-base.yaml` の `ops: true` が決める** —
 * ここに名前を並べない（設計原則 3）。
 */
export function DriversPanel() {
  const telemetry = useConsoleStore((s) => s.telemetry)
  const layout = useConsoleStore((s) => s.layout)

  // gateway は telemetry 宣言があれば必ず送る。null は「まだ 1 通も来ていない」。
  if (telemetry === null) return null

  if (!LAYOUT_DEFAULTS[layout].showAllTelemetry) {
    const items = [
      ...telemetry.drivers.flatMap((d) => opsItems(d.items)),
      ...opsItems(telemetry.derived),
    ]
    return (
      <section className="panel drivers ops" data-testid="drivers">
        <h2>主要テレメトリ</h2>
        {items.length === 0 ? (
          <p className="muted" data-testid="ops-telemetry-empty">
            ops に出す項目が宣言されていない（cr2-base.yaml の ops: true）。
          </p>
        ) : (
          items.map((item) => (
            <div
              key={item.name}
              className={`derived-row level-${item.level}`}
              data-testid={`ops-telemetry-${item.name}`}
            >
              <span className={`badge level-${item.level}`}>{LEVEL_MARK[item.level]}</span>
              <Reading item={item} />
            </div>
          ))
        )}
      </section>
    )
  }

  return (
    <section className="panel drivers" data-testid="drivers">
      <h2>ドライバ（{telemetry.drivers.length}）</h2>
      {telemetry.drivers.map((driver) => (
        <DriverCard key={driver.driver} driver={driver} />
      ))}

      {/* 単一のドライバに属さないもの。最下段に別枠で出す。 */}
      {telemetry.derived.length > 0 && (
        <div className="derived" data-testid="derived">
          {telemetry.derived.map((item) => (
            <div
              key={item.name}
              className={`derived-row level-${item.level}`}
              data-testid={`derived-${item.name}`}
            >
              <span className={`badge level-${item.level}`}>{LEVEL_MARK[item.level]}</span>
              <Reading item={item} />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function DriverCard({ driver }: { driver: TelemetryDriver }) {
  const [open, setOpen] = useState(false)
  const level = worstLevel(driver.items)
  const down = isDown(driver)

  return (
    <article
      className={`driver level-${down ? 'crit' : level}`}
      data-testid={`driver-${driver.driver}`}
    >
      <button
        type="button"
        className="driver-summary"
        data-testid={`driver-toggle-${driver.driver}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="driver-caret">{open ? '▾' : '▸'}</span>
        <span className="driver-name">{driver.driver}</span>

        {down ? (
          // **「値が無い」ではなく「起動していない」と言う。** これが分からないと
          // 現地でセンサを疑って時間を溶かす。
          <span className="badge state-down" data-testid={`driver-down-${driver.driver}`}>
            起動していない
          </span>
        ) : isOffByDeclaration(driver) ? (
          // このモードでは起動しない宣言のもの（realsense など）。
          // 赤くしない。起動していなくて当たり前。値が来ていれば普通に出す。
          <span className="badge" data-testid={`driver-off-${driver.driver}`}>
            対象外
          </span>
        ) : (
          <>
            <span className={`badge level-${level}`}>{LEVEL_MARK[level]}</span>
            {summaryItems(driver.items).map((item) => (
              <Reading key={item.name} item={item} compact />
            ))}
          </>
        )}
      </button>

      {open && (
        <div className="driver-detail" data-testid={`driver-detail-${driver.driver}`}>
          {driver.items.map((item) => (
            <Reading key={item.name} item={item} />
          ))}
        </div>
      )}
    </article>
  )
}

function Reading({ item, compact = false }: { item: TelemetryItem; compact?: boolean }) {
  const ratio = barRatio(item)
  // **概要行と詳細で id を分ける。** 異常な項目は両方に出るので、同じ id だと
  // DOM に 2 つ並び、どちらを見ているのか指定できないテストになる。
  const id = compact ? `summary-${item.name}` : item.name

  return (
    <span
      className={`reading level-${item.level}${compact ? ' compact' : ''}`}
      data-testid={`telemetry-${id}`}
      title={item.description || item.topic}
    >
      <span className="reading-name">{item.name}</span>

      {item.widget === 'heading' && item.value !== null ? (
        // 角度は数字より向きの絵のほうが速く読める。数字も残す
        // （どちらが正面かを絵だけで確かめるのは無理）。
        <span className="reading-value" data-testid={`telemetry-value-${id}`}>
          <span
            className="heading-arrow"
            style={{ transform: `rotate(${-item.value}deg)` }}
            aria-hidden="true"
          >
            ↑
          </span>
          {formatValue(item)}
        </span>
      ) : (
        <span className="reading-value" data-testid={`telemetry-value-${id}`}>
          {formatValue(item)}
        </span>
      )}

      {ratio !== null && !compact && (
        <span className="reading-bar" data-testid={`telemetry-bar-${id}`}>
          <span className="reading-fill" style={{ width: `${(ratio * 100).toFixed(1)}%` }} />
        </span>
      )}

      {/* 途絶えた値は消さずに、いつのものかを添える。消すと「不明」と
          区別が付かず、残したままだと最新に見える。 */}
      {item.level === 'stale' && (
        <span className="reading-age" data-testid={`telemetry-age-${id}`}>
          {formatAge(item.age)}
        </span>
      )}
    </span>
  )
}
