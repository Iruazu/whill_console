import { expect, test } from '@playwright/test'

/** 実際の gateway + dispatch_node に対して配車する。既定では skip。
 *
 *     whill run --robot cr2-01 --mode mock --gateway
 *     WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live-dispatch.spec.ts
 */
const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test('行き先を押すと車体が動き出し、取り消しで止まる', async ({ page }) => {
  test.skip(!LIVE, 'gateway と dispatch_node が要る。WHILL_LIVE=1 で有効化')
  test.setTimeout(90_000)
  await page.addInitScript(
    ([k, v]) => window.localStorage.setItem(k, v),
    ['whill.gateway.token', TOKEN],
  )
  await page.goto('/')
  await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, { timeout: 20000 })
  // 接続直後に地点一覧が出ること。dispatch_node は latched ではなく再送なので、
  // gateway が保持していないと最初の 1 秒は空のパネルになる。
  await expect(page.getByTestId('dispatch-to-east')).toBeVisible({ timeout: 10000 })

  const pose = async () =>
    (await page.evaluate(() => (window as any).__whill.pose)) as { x: number }
  const phase = () => page.getByTestId('dispatch-phase')

  // **先に止める。** 前回の実行が残した job が走っていると、こちらの
  // 投入は FIFO の後ろに並ぶだけ（`whill_dispatch` は preempt しない）。
  // 「走行中」の表示は前の job のもので、車体は別の方向へ進んでいく。
  if (await phase().textContent() === '走行中') {
    await page.getByTestId('dispatch-cancel').click()
    await expect(phase()).not.toHaveText('走行中', { timeout: 15000 })
    await page.waitForTimeout(2000)   // 減速しきるまで
  }

  const start = await pose()

  // **いま居る場所から遠いほうへ配車する。** 直前の実行で東端に着いたまま
  // だと、東端をもう一度指しても動かず「配線が壊れている」と読めてしまう。
  const target = start.x < 0 ? 'east' : 'west'
  const targetX = target === 'east' ? 7 : -7
  await page.getByTestId(`dispatch-to-${target}`).click()
  await expect(page.getByTestId('dispatch-phase')).toHaveText('走行中', { timeout: 15000 })
  await expect(page.getByTestId('dispatch-progress')).toBeVisible()
  await page.screenshot({ path: '../docs/screenshots/live-dispatch.png', fullPage: true })

  // 進捗が絵として進むだけでなく、実際に車体が近づいていること。
  //
  // 待ち時間は短くしない。mock は `desired_linear_vel` 0.3 m/s で、しかも
  // 逆を向いていれば先に旋回する。4 秒だと旋回だけで終わり、**配線が
  // 正しくても失敗する**（実際に踏んだ）。
  await page.waitForTimeout(12000)
  const before = Math.abs(start.x - targetX)
  expect(Math.abs((await pose()).x - targetX)).toBeLessThan(before - 0.5)

  await page.getByTestId('dispatch-cancel').click()
  await expect(page.getByTestId('dispatch-phase')).toHaveText('取り消し', { timeout: 15000 })

  // 取り消したあとは止まっていること。「取り消し」と出ているのに走り続けるのが
  // 一番まずい。
  const afterCancel = await pose()
  await page.waitForTimeout(3000)
  expect(Math.abs((await pose()).x - afterCancel.x)).toBeLessThan(0.2)
})
