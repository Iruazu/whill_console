import { expect, test } from '@playwright/test'

/** 実際の gateway に繋いで確かめるテスト。
 *
 * **既定では skip する。** gateway と mock スタックが動いている必要があり、
 * CI では用意できない。動かすとき:
 *
 *     WHILL_GATEWAY_TOKEN=... whill run --robot cr2-01 --mode mock --gateway
 *     WHILL_LIVE=1 WHILL_LIVE_TOKEN=... pnpm exec playwright test tests/live.spec.ts
 *
 * skip されたことは Playwright のレポートに出る。「全部 skip で緑」を
 * 見逃さないため、実行時は件数を確認すること。
 */

const LIVE = process.env.WHILL_LIVE === '1'
const TOKEN = process.env.WHILL_LIVE_TOKEN ?? ''

test.describe('実 gateway との接続', () => {
  test.skip(!LIVE, 'gateway が要る。WHILL_LIVE=1 と WHILL_LIVE_TOKEN で有効化')

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value),
      ['whill.gateway.token', TOKEN],
    )
    await page.goto('/')
  })

  test('接続すると costmap と params が届く', async ({ page }) => {
    await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, {
      timeout: 20_000,
    })

    const snapshot = await page.evaluate(async () => {
      await new Promise((resolve) => setTimeout(resolve, 4000))
      return (window as unknown as { __whill?: Record<string, unknown> }).__whill
    })

    // 全量 costmap は接続時にしか来ない（ADR-0002）。届いていなければ
    // gateway が保持していないということ。
    expect(snapshot?.costmaps).toHaveProperty('local')
    expect(snapshot?.params).toBeGreaterThan(0)
    expect(snapshot?.unhandled).toBe(0)
  })

  test('gateway を落として上げ直すと自動で再接続する', async ({ page }) => {
    test.setTimeout(90_000)
    await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, {
      timeout: 20_000,
    })

    // このあいだに手で gateway を落として上げ直す（別ターミナル）
    const seen = new Set<string>()
    for (let i = 0; i < 50; i += 1) {
      const state = await page.evaluate(
        () =>
          (window as unknown as { __whill?: { connection: string } }).__whill
            ?.connection,
      )
      if (state) seen.add(state)
      await page.waitForTimeout(1000)
    }

    expect([...seen]).toContain('disconnected')
    await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/, {
      timeout: 20_000,
    })
  })
})
