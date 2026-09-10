import { expect, test } from '@playwright/test'

const SHOT_DIR = '../docs/screenshots'

const TOKEN_KEY = 'whill.gateway.token'

/** トークンを入れた状態でアプリを開く。
 *
 * 未設定だと TokenGate が出るので、レイアウトを見るテストでは先に入れておく。
 * gateway は起動していないので接続は失敗するが、**それでも画面は成立する**
 * ことを見たい（繋がらないと何も出ない、では現地で切り分けができない）。
 */
async function openWithToken(page: import('@playwright/test').Page) {
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [TOKEN_KEY, 'e2e-token-1234'],
  )
  await page.goto('/')
}

test.describe('console のスクリーンショット', () => {
  test('トークン未設定ならゲートが出る', async ({ page }) => {
    // 「繋がらない」とだけ出して放置すると、原因（未設定）に辿り着けない
    await page.goto('/')
    await expect(page.getByTestId('token-gate')).toBeVisible()
    await expect(page.getByTestId('token-input')).toBeVisible()
  })

  test('トークンを入れるとコンソールに入る', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('token-input').fill('e2e-token-1234')
    await page.getByTestId('token-submit').click()
    await expect(page.getByTestId('topbar')).toBeVisible()
  })

  test('dev レイアウトが描画される', async ({ page }, testInfo) => {
    const errors: string[] = []
    // 描画バグの多くは例外として出る。撮れた画像が正しく見えても、
    // console エラーがあれば失敗にする。
    //
    // ただし WebSocket の接続失敗は除く。このテストは gateway を起動せずに
    // 走らせる（描画だけを見る）ので、接続が拒否されるのは想定どおり。
    // ここを除外しないと、本当の描画バグが「いつもの赤」に埋もれる。
    const expected = /WebSocket connection to .* failed/
    const record = (text: string) => {
      if (!expected.test(text)) errors.push(text)
    }
    page.on('pageerror', (error) => record(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error') record(message.text())
    })

    await openWithToken(page)
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

  test('gateway 未接続でも画面が成立し、理由が出る', async ({ page }) => {
    await openWithToken(page)
    // 未接続でも E-stop は押せる状態であること。押せなくなると、
    // 通信が怪しいときに一番使いたいものが使えない。
    // （押しても届かないことの明示は #22 で扱う）
    await expect(page.getByTestId('estop')).toBeEnabled()

    // 「繋がらない」だけでなく状態が読めること。トークンが違うのか
    // gateway が落ちているのか区別できないと現地で切り分けられない。
    const badge = page.getByTestId('connection')
    await expect(badge).toBeVisible()
    await expect(badge).not.toHaveText(/gateway 接続$/)
  })

  test('768px で ops 相当の幅が横スクロールしない', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 })
    await openWithToken(page)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, '横方向にはみ出している').toBeLessThanOrEqual(0)
  })
})
