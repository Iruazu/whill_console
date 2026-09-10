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

  test('合成 costmap を流し込むと実際に地図が描かれる', async ({ page }, testInfo) => {
    // gateway 抜きで「地図が描かれる」ことを確かめる。真っ黒のスクリーン
    // ショットを撮って「描画できている」と誤読しないため、canvas の
    // 中身を実際に読んで色の種類を数える。
    await openWithToken(page)
    await expect(page.getByTestId('overview-empty')).toBeVisible()

    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (frame: Record<string, unknown>) => void
      }).__whillIngest

      // 20x20 の格子。左半分を空き、右半分を占有、上 2 行を未知にする。
      const width = 20
      const height = 20
      const rle: number[] = []
      for (let row = 0; row < height; row += 1) {
        const value = row >= height - 2 ? -1 : 0
        rle.push(value, width / 2)
        rle.push(row >= height - 2 ? -1 : 100, width / 2)
      }
      ingest({
        type: 'costmap', scope: 'local', frame_id: 'map', resolution: 0.5,
        width, height, origin_x: -5, origin_y: -5, rle, ratio: 0.1,
        stamp: 1, seq: 1,
      })
      ingest({ type: 'pose', x: 0, y: 0, yaw: 0.4, frame_id: 'map', source: 'test', stamp: 1 })
      ingest({
        type: 'path', frame_id: 'map',
        points: [[-3, -3], [0, 0], [3, 2]], stamp: 1,
      })
      ingest({
        type: 'scan', frame_id: 'velodyne', angle_min: 0,
        angle_increment: Math.PI / 8, range_max: 10,
        ranges: Array.from({ length: 16 }, (_, i) => 2 + (i % 3)), stamp: 1,
      })
    })

    await expect(page.getByTestId('overview-empty')).toHaveCount(0)

    const colours = await page.evaluate(() => {
      const canvas = document.querySelector(
        '[data-testid="overview-canvas"]',
      ) as HTMLCanvasElement
      const ctx = canvas.getContext('2d')!
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      const seen = new Set<string>()
      for (let i = 0; i < data.length; i += 4) {
        seen.add(`${data[i]},${data[i + 1]},${data[i + 2]}`)
      }
      return [...seen]
    })

    // 背景 + 格子 + 空き + 占有 + 未知 + 経路 + 車体 + LiDAR。
    // 真っ黒（1 色）なら描けていない。
    expect(colours.length).toBeGreaterThan(5)

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-overview.png`,
      fullPage: true,
    })
  })

  test('進行方向上に切り替えると絵が変わる', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (frame: Record<string, unknown>) => void
      }).__whillIngest
      ingest({
        type: 'costmap', scope: 'local', frame_id: 'map', resolution: 0.5,
        width: 20, height: 20, origin_x: -5, origin_y: -5,
        rle: [0, 200, 100, 200], ratio: 0.1, stamp: 1, seq: 1,
      })
      ingest({ type: 'pose', x: 0, y: 0, yaw: 1.0, frame_id: 'map', source: 'test', stamp: 1 })
    })

    const snapshot = async () =>
      page.evaluate(() => {
        const canvas = document.querySelector(
          '[data-testid="overview-canvas"]',
        ) as HTMLCanvasElement
        return canvas.toDataURL().slice(0, 512)
      })

    const before = await snapshot()
    await page.getByTestId('heading-up').check()
    await page.waitForTimeout(200)
    expect(await snapshot()).not.toBe(before)
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
