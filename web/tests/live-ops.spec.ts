import { expect, test } from '@playwright/test'

/** 実際の gateway に対して ops レイアウトで配車する。既定では skip。
 *
 *     whill run --robot cr2-01 --mode mock --gateway
 *     WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live-ops.spec.ts
 */
const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test('tablet 幅の ops で配車と主要テレメトリが使える', async ({ page }) => {
  test.skip(!LIVE, 'gateway と dispatch_node が要る。WHILL_LIVE=1 で有効化')
  test.setTimeout(90_000)
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.addInitScript(
    ([k, v]) => {
      window.localStorage.setItem(k, v)
      window.localStorage.setItem('whill.layout', 'ops')
    },
    ['whill.gateway.token', TOKEN],
  )
  await page.goto('/')
  await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, { timeout: 20000 })

  // E-stop はスクロールなしで押せる位置にあり、接続中は押せる。
  await expect(page.getByTestId('estop')).toBeInViewport()
  await expect(page.getByTestId('estop')).toBeEnabled()

  // 主要テレメトリに実測値が出る。
  await expect(page.getByTestId('ops-telemetry-battery')).not.toContainText('—', { timeout: 15000 })
  await expect(page.getByTestId('ops-telemetry-scan_rate')).not.toContainText('—')

  // 追従・進行方向上で開く。
  await expect(page.getByTestId('follow-robot')).toBeChecked()
  await expect(page.getByTestId('heading-up')).toBeChecked()

  const pose = async () =>
    (await page.evaluate(() => (window as any).__whill.pose)) as { x: number }
  const phase = page.getByTestId('dispatch-phase')
  if ((await phase.textContent()) === '走行中') {
    await page.getByTestId('dispatch-cancel').click()
    await expect(phase).not.toHaveText('走行中', { timeout: 15000 })
    await page.waitForTimeout(2000)
  }
  const start = await pose()
  const target = start.x < 0 ? 'east' : 'west'
  const targetX = target === 'east' ? 7 : -7
  await page.getByTestId(`dispatch-to-${target}`).click()
  await expect(phase).toHaveText('走行中', { timeout: 15000 })
  await page.waitForTimeout(12000)
  expect(Math.abs((await pose()).x - targetX)).toBeLessThan(Math.abs(start.x - targetX) - 0.5)

  await page.screenshot({ path: '../docs/screenshots/live-ops.png' })

  const overflow = await page.evaluate(() => ({
    x: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    y: document.documentElement.scrollHeight - document.documentElement.clientHeight,
  }))
  expect(overflow.x).toBeLessThanOrEqual(0)
  expect(overflow.y).toBeLessThanOrEqual(0)

  await page.getByTestId('dispatch-cancel').click()
  await expect(phase).toHaveText('取り消し', { timeout: 15000 })
})
