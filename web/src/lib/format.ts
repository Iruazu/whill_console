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
