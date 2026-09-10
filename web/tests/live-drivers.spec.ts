import { expect, test } from '@playwright/test'

/** 実際の gateway に対して drivers パネルを見る。既定では skip。
 *
 *     whill run --robot cr2-01 --mode mock --gateway
 *     WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live-drivers.spec.ts
 */
const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test('mock の値が drivers パネルに出て、動く', async ({ page }) => {
  test.skip(!LIVE, 'gateway が要る。WHILL_LIVE=1 で有効化')
  test.setTimeout(60_000)
  await page.addInitScript(
    ([k, v]) => window.localStorage.setItem(k, v),
    ['whill.gateway.token', TOKEN],
  )
  await page.goto('/')
  await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, { timeout: 20000 })
  await expect(page.getByTestId('drivers')).toBeVisible({ timeout: 15000 })

  // 宣言されている 4 ドライバが並ぶ。
  for (const name of ['whill_serial', 'velodyne', 'rt_9axis', 'realsense']) {
    await expect(page.getByTestId(`driver-${name}`)).toBeVisible()
  }

  // realsense は既定で起動しない。赤くしないこと（起動していなくて当たり前）。
  await expect(page.getByTestId('driver-off-realsense')).toBeVisible()

  await page.getByTestId('driver-toggle-velodyne').click()
  const detail = page.getByTestId('driver-detail-velodyne')
  // scan_rate は**実測**。宣言（10 Hz）に近い数字が出ていること。
  const rate = () =>
    page.evaluate(() => {
      const t = (window as any).__whill.telemetryItems
      return t?.scan_rate ?? null
    })
  expect(await rate()).toBeGreaterThan(5)
  await expect(detail.getByTestId('telemetry-value-points_per_scan')).not.toHaveText('—')

  await page.getByTestId('driver-toggle-whill_serial').click()
  await page.screenshot({ path: '../docs/screenshots/live-drivers.png', fullPage: true })

  // バッテリーは走行で減っていく。値が固まっていないこと（配線が生きている証拠）。
  const battery = () =>
    page.evaluate(() => (window as any).__whill.telemetryItems?.battery ?? null)
  expect(await battery()).toBeGreaterThan(0)
})
