import { expect, test } from '@playwright/test'

const SHOT_DIR = '../docs/screenshots'

test.describe('console のスクリーンショット', () => {
  test('dev レイアウトが描画される', async ({ page }, testInfo) => {
    const errors: string[] = []
    // 描画バグの多くは例外として出る。撮れた画像が正しく見えても、
    // console エラーがあれば失敗にする。
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })

    await page.goto('/')
    await expect(page.getByTestId('topbar')).toBeVisible()
    await expect(page.getByTestId('overview2d')).toBeVisible()
    await expect(page.getByTestId('params')).toBeVisible()
    await expect(page.getByTestId('estop')).toBeVisible()

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-dev.png`,
      fullPage: true,
    })

    expect(errors, `console エラー: ${errors.join(' / ')}`).toHaveLength(0)
  })

  test('gateway 未接続でも操作不能にならない', async ({ page }) => {
    await page.goto('/')
    // 未接続でも E-stop は押せる状態であること。押せなくなると、
    // 通信が怪しいときに一番使いたいものが使えない。
    await expect(page.getByTestId('estop')).toBeEnabled()
    await expect(page.getByText('gateway 未接続')).toBeVisible()
  })

  test('768px で ops 相当の幅が横スクロールしない', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 })
    await page.goto('/')
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, '横方向にはみ出している').toBeLessThanOrEqual(0)
  })
})
