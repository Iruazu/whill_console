import { expect, test } from '@playwright/test'

/** 実 gateway で、俯瞰図のクリックが costmap まで届くか。既定では skip。
 *
 *     WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live-obstacles.spec.ts
 */
const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test('俯瞰図のクリックで仮想障害物を置き、消せる', async ({ page }) => {
  test.skip(!LIVE, 'gateway が要る。WHILL_LIVE=1 と WHILL_LIVE_TOKEN で有効化')
  test.setTimeout(90_000)
  await page.addInitScript(
    ([k, v]) => window.localStorage.setItem(k, v),
    ['whill.gateway.token', TOKEN],
  )
  await page.goto('/')
  await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, { timeout: 20000 })
  await expect(page.getByTestId('obstacle-count')).toContainText('0', { timeout: 10000 })

  await page.getByTestId('placing-mode').check()
  const canvas = page.getByTestId('overview-canvas')
  const box = (await canvas.boundingBox())!

  // 中心から少し右（車体の前方あたり）に置く
  await canvas.click({ position: { x: box.width / 2 + 80, y: box.height / 2 } })
  await expect(page.getByTestId('obstacle-count')).toContainText('1', { timeout: 10000 })
  console.log('PLACED')

  await page.screenshot({ path: '../docs/screenshots/live-obstacles.png', fullPage: true })

  // 同じところをクリックすると消える
  await canvas.click({ position: { x: box.width / 2 + 80, y: box.height / 2 } })
  await expect(page.getByTestId('obstacle-count')).toContainText('0', { timeout: 10000 })
  console.log('REMOVED')
})
