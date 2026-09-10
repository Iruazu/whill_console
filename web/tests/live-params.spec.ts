import { expect, test } from '@playwright/test'

/** 実 gateway でスライダー → Nav2 の反映を確かめる。既定では skip する
 *  （gateway と mock スタックが要る）。
 *
 *      WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live-params.spec.ts
 */
const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test('実 gateway でスライダーを動かすと Nav2 に反映される', async ({ page }) => {
  test.skip(!LIVE, 'gateway が要る。WHILL_LIVE=1 と WHILL_LIVE_TOKEN で有効化')
  test.setTimeout(60_000)
  await page.addInitScript(
    ([k, v]) => window.localStorage.setItem(k, v),
    ['whill.gateway.token', TOKEN],
  )
  await page.goto('/')
  await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, { timeout: 20000 })

  const key = 'controller_server.FollowPath.min_lookahead_dist'
  await expect(page.getByTestId(`param-${key}`)).toBeVisible({ timeout: 15000 })

  // 数値入力から確定させる（スライダーの pointer 操作より確実）
  const input = page.getByTestId(`input-${key}`)
  await input.fill('0.85')
  await input.press('Enter')
  await page.waitForTimeout(1500)

  const log = page.getByTestId('change-log')
  await expect(log).toContainText('OK')
  console.log('LOG:', (await log.textContent())?.slice(0, 160))

  // 範囲外を入れて拒否されること
  await input.fill('9.9')
  await input.press('Enter')
  await page.waitForTimeout(1500)
  console.log('LOG2:', (await log.textContent())?.slice(0, 220))

  // 拒否されたあと、入力欄が実際の値に戻っていること。
  // 戻らないと「効いたように見えて効いていない」表示になる。
  await expect(input).toHaveValue('0.85')

  await page.screenshot({ path: '../docs/screenshots/live-params.png', fullPage: true })
})
