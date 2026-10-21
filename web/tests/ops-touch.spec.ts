import { expect, test } from '@playwright/test'

/** ops の操作要素が指で押せる大きさかを**実寸で**検査する。
 *
 * 屋外・手袋・走行中の揺れという条件は実機でしか確かめられないが、
 * **大きさと間隔は今測れる。** 実測して決めた基準:
 *
 *   - 触る要素は 44px 角以上（Apple HIG の最小）
 *   - E-STOP と行き先は 56px 以上（片手・手袋を想定して 1 段上げる）
 *   - 隣り合う操作は 12px 以上あける
 *
 * 入れる前の実測（768px、2026-09-19）:
 *   E-STOP 100x37、行き先の間隔 6px、チェックボックス 13x13。
 *   **いちばん押さねばならない E-STOP が一番小さかった。**
 *
 * dev（机の上、マウス）は対象外。ops だけを見る。
 */

const MIN_TOUCH = 44
const MIN_PRIMARY = 56
const MIN_GAP = 12

/** 主要操作（押し間違い・押し損ねの代償が大きいもの）。 */
const PRIMARY = ['estop', 'dispatch-to-west', 'dispatch-to-center', 'dispatch-to-east']

interface Target {
  what: string
  width: number
  height: number
  gap: number | null
}

async function measure(page: import('@playwright/test').Page): Promise<Target[]> {
  return page.evaluate(() => {
    type Box = { left: number; right: number; top: number; bottom: number }
    const out: { what: string; width: number; height: number; gap: number | null }[] = []
    const seen: { box: Box; what: string }[] = []
    document.querySelectorAll('button, select, input').forEach((el) => {
      const raw = el.getBoundingClientRect()
      if (raw.width === 0 || raw.height === 0) return
      // チェックボックスは入れ物（label）が当たり判定。13px の四角を狙わせない。
      const target = el.closest('label') ?? el
      const rect = target.getBoundingClientRect()
      const what = el.getAttribute('data-testid') ?? el.tagName.toLowerCase()
      let gap: number | null = null
      for (const other of seen) {
        const dx = Math.max(other.box.left - rect.right, rect.left - other.box.right, 0)
        const dy = Math.max(other.box.top - rect.bottom, rect.top - other.box.bottom, 0)
        const distance = Math.hypot(dx, dy)
        gap = gap === null ? distance : Math.min(gap, distance)
      }
      seen.push({ box: rect, what })
      out.push({ what, width: Math.round(rect.width), height: Math.round(rect.height), gap })
    })
    return out
  })
}

async function openOps(page: import('@playwright/test').Page) {
  await page.addInitScript(
    ([key, token, layout]) => {
      window.localStorage.setItem(key, token)
      window.localStorage.setItem('whill.layout', layout)
    },
    ['whill.gateway.token', 'e2e-token-1234', 'ops'],
  )
  await page.goto('/')
  await page.evaluate(() => {
    const w = window as unknown as { __whillIngest: (f: Record<string, unknown>) => void }
    w.__whillIngest({
      type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
      moving: false, estop: false, clients: 1, preset: null, stamp: 1,
    })
    w.__whillIngest({
      type: 'dispatch_waypoints',
      waypoints: [
        { name: 'west', label: '西端', x: -7, y: 0, yaw: 0 },
        { name: 'center', label: '中央', x: 0, y: 0, yaw: 0 },
        { name: 'east', label: '東端', x: 7, y: 0, yaw: 0 },
      ],
    })
    w.__whillIngest({
      type: 'dispatch_state', job_id: '', phase: 'ACTIVE', waypoint: 'east',
      progress: 0.3, queue_len: 0, stamp: 1,
    })
  })
  await page.waitForTimeout(300)
}

test.describe('ops の押せる大きさ', () => {
  test.skip(({ viewport }) => (viewport?.width ?? 0) > 900, 'ops の幅でだけ見る')

  test('触る要素はすべて 44px 角以上', async ({ page }) => {
    await openOps(page)
    const small = (await measure(page)).filter(
      (t) => t.width < MIN_TOUCH || t.height < MIN_TOUCH)
    expect(small, `小さすぎる: ${JSON.stringify(small)}`).toEqual([])
  })

  test('E-STOP と行き先は 56px 以上', async ({ page }) => {
    await openOps(page)
    const targets = await measure(page)
    for (const name of PRIMARY) {
      const found = targets.find((t) => t.what === name)
      expect(found, `${name} が見つからない`).toBeTruthy()
      expect(found!.height, `${name} の高さ`).toBeGreaterThanOrEqual(MIN_PRIMARY)
    }
  })

  test('隣り合う操作は 12px 以上あく', async ({ page }) => {
    await openOps(page)
    const tight = (await measure(page)).filter((t) => t.gap !== null && t.gap < MIN_GAP)
    expect(tight, `近すぎる: ${JSON.stringify(tight)}`).toEqual([])
  })

  test('E-STOP 作動中も解除ボタンが同じ大きさで同じ場所にある', async ({ page }) => {
    // 押し間違いが一番危ないのはこの状態。解除が小さくなったり動いたりしない。
    await openOps(page)
    const before = (await measure(page)).find((t) => t.what === 'estop')!
    await page.evaluate(() => {
      const w = window as unknown as { __whillIngest: (f: Record<string, unknown>) => void }
      w.__whillIngest({
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
        moving: false, estop: true, clients: 1, preset: null, stamp: 2,
      })
    })
    await expect(page.getByTestId('estop-banner')).toBeVisible()
    const after = (await measure(page)).find((t) => t.what === 'estop')!
    expect(after.height).toBeGreaterThanOrEqual(MIN_PRIMARY)
    expect(after.width).toBeGreaterThanOrEqual(before.width)
  })
})
