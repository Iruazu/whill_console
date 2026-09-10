import { expect, test } from '@playwright/test'

/** 実 bag 再生を俯瞰図に出す。既定では skip。
 *
 *     whill run --robot cr2-01 --mode replay --bag bags/2026-07-31-campus --gateway
 *     WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live-replay.spec.ts
 */
const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test('bag 再生が俯瞰図に再現される', async ({ page }) => {
  test.skip(!LIVE, 'gateway と bag 再生が要る。WHILL_LIVE=1 で有効化')
  test.setTimeout(60_000)
  await page.addInitScript(
    ([k, v]) => window.localStorage.setItem(k, v),
    ['whill.gateway.token', TOKEN],
  )
  await page.goto('/')
  await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, { timeout: 20000 })
  await expect(page.getByTestId('mode')).toHaveText('replay')

  await page.getByTestId('follow-robot').check()
  await page.waitForTimeout(6000)

  const info = await page.evaluate(() => (window as any).__whill)
  console.log('STORE:', JSON.stringify({ costmaps: info.costmaps, pose: info.pose }))
  expect(info.costmaps.local ?? info.costmaps.global).toBeTruthy()

  await page.screenshot({ path: '../docs/screenshots/live-replay.png', fullPage: true })
})
