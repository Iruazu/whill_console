import { expect, test } from '@playwright/test'

/** 実 gateway で E-stop ボタンが車体を止めるか。既定では skip する。
 *
 *     WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live-estop.spec.ts
 */
const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test('E-stop ボタンで自律走行が止まり、解除しても再開しない', async ({ page }) => {
  test.skip(!LIVE, 'gateway が要る。WHILL_LIVE=1 と WHILL_LIVE_TOKEN で有効化')
  test.setTimeout(90_000)
  await page.addInitScript(
    ([k, v]) => window.localStorage.setItem(k, v),
    ['whill.gateway.token', TOKEN],
  )
  await page.goto('/')
  await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, { timeout: 20000 })

  // 往復遅延が測れていること
  await expect(page.getByTestId('latency')).toContainText('ms', { timeout: 10000 })
  console.log('LATENCY:', await page.getByTestId('latency').textContent())

  await page.getByTestId('estop').click()
  await expect(page.getByTestId('estop-banner')).toBeVisible({ timeout: 10000 })
  console.log('ESTOP: banner shown')

  // 外から /whill/controller/cmd_vel を観測できるだけの時間、保持する。
  // すぐ解除すると計測ウィンドウから外れて「効いていない」ように見える。
  await page.waitForTimeout(6000)

  await page.screenshot({ path: '../docs/screenshots/live-estop.png', fullPage: true })

  // 解除は確認を挟む
  await page.getByTestId('estop').click()
  await expect(page.getByTestId('estop-release-dialog')).toBeVisible()
  await expect(page.getByTestId('estop-release-dialog')).toContainText('再開しない')
  await page.getByTestId('estop-release-confirm').click()
  await expect(page.getByTestId('estop-banner')).toHaveCount(0, { timeout: 10000 })
  console.log('ESTOP: released')
})
