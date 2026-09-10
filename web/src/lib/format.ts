/** 表示用の整形。 */

/** 往復遅延の表示。
 *
 * localhost では 1 ms を切る。素直に丸めると「0 ms」になり、**未測定や
 * 故障と紛らわしい**（実際に画面で 0 ms を見て一瞬疑った）。1 ms 未満は
 * そうと分かる形で出す。
 */
export function formatLatency(ms: number | null): string {
  if (ms === null) return '—'
  if (ms < 1) return '<1 ms'
  return `${Math.round(ms)} ms`
}

/** 秒を `m:ss` にする。bag の再生位置に使う。
 *
 * 代表 bag が 235 秒なので時間は出さない。1 時間を超える bag を再生する
 * ようになったら `h:mm:ss` に広げること。
 */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—'
  const total = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(total % 60).padStart(2, '0')}`
}

/** 再生速度の表示。
 *
 * 観測値なので 1.00 ちょうどにはならない。小数 2 桁まで出すと数字が
 * 落ち着かず読みにくいので 1 桁に丸める。
 */
export function formatRate(rate: number | null): string {
  if (rate === null || !Number.isFinite(rate)) return '—'
  return `${rate.toFixed(1)}x`
}
