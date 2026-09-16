/** カメラ画像の到着から実測レートを出す（ADR-0007）。
 *
 * **宣言値を出さない。** 見たいのは「6 Hz で流すつもりなのに 1 Hz しか来ていない」で、
 * 設定値を表示する実装はその目的を反転させる（drivers テレメトリの `__rate` と同じ）。
 *
 * 純粋関数だけ置く。時刻は全部引数で受け取る。
 */

/** これより古い到着は捨てる。短いと数字が暴れ、長いと止まったのに気づけない。 */
export const RATE_WINDOW_MS = 3000

/** 窓に残す最大件数。30 fps の実機でも 3 秒ぶんで足りる。 */
export const RATE_MAX_SAMPLES = 120

export function pushArrival(times: number[], now: number): number[] {
  const next = [...times, now].slice(-RATE_MAX_SAMPLES)
  return next.filter((t) => now - t <= RATE_WINDOW_MS)
}

/** 実測レート [Hz]。2 枚未満なら null（「0 Hz」と「まだ来ていない」は別）。 */
export function measuredHz(times: number[], now: number): number | null {
  const window = times.filter((t) => now - t <= RATE_WINDOW_MS)
  if (window.length < 2) return null
  // 窓の長さではなく最初と最後の差で割る。立ち上がりで過小に出るのを避ける。
  const span = window[window.length - 1] - window[0]
  if (span <= 0) return null
  return ((window.length - 1) / span) * 1000
}
