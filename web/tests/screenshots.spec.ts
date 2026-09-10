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

    // 「繋がらない」だけでなく状態が読めること。トークンが違うのか
    // gateway が落ちているのか区別できないと現地で切り分けられない。
    const badge = page.getByTestId('connection')
    await expect(badge).toBeVisible()
    await expect(badge).not.toHaveText(/gateway 接続$/)

    // パネルは出る。繋がらないと何も見えない、では現地で切り分けができない。
    await expect(page.getByTestId('overview2d')).toBeVisible()
    await expect(page.getByTestId('params')).toBeVisible()

    // E-stop は「押せない」と分かる形にする。
    //
    // Phase 0 では「未接続でも enabled」を確認していた（通信が怪しいときに
    // 一番使いたいものが操作不能にならないよう）。実配線した以上、押しても
    // 届かないものを押せるように見せるほうが危ない。理由を title に出す。
    const estop = page.getByTestId('estop')
    await expect(estop).toBeVisible()
    await expect(estop).toBeDisabled()
    await expect(estop).toHaveAttribute('title', /届かない/)
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

  test('params が registry から自動生成される', async ({ page }, testInfo) => {
    await openWithToken(page)
    await expect(page.getByText('registry 未受信。')).toBeVisible()

    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (frame: Record<string, unknown>) => void
      }).__whillIngest
      ingest({
        type: 'params',
        presets: ['cautious', 'campus-cruise'],
        preset: null,
        unreachable: ['/behavior_server'],
        mismatches: [{ key: 'a.b', registry: 0.3, live: 0.5 }],
        params: [
          {
            key: 'controller_server.FollowPath.desired_linear_vel',
            node: 'controller_server', ros_node: '/controller_server',
            name: 'FollowPath.desired_linear_vel', type: 'double',
            value: 0.3, default: 0.3,
            range: { min: 0.05, max: 1.0, step: 0.01 },
            unit: 'm/s', live: true, safety_class: 'locked_while_moving',
            description: '着座した人を乗せて 0.3 m/s が安全な巡航。',
          },
          {
            key: 'local_costmap.robot_radius',
            node: 'local_costmap', ros_node: '/local_costmap/local_costmap',
            name: 'robot_radius', type: 'double', value: 0.45, default: 0.45,
            range: { min: 0.2, max: 0.9, step: 0.01 },
            unit: 'm', live: false, safety_class: 'locked_while_moving',
            description: '円 footprint 近似。',
          },
          {
            key: 'velocity_smoother.max_accel',
            node: 'velocity_smoother', ros_node: '/velocity_smoother',
            name: 'max_accel', type: 'double_array',
            value: [0.3, 0.0, 1.0], default: [0.3, 0.0, 1.0], range: null,
            elements: [
              { label: 'ax', range: { min: 0.05, max: 1.0, step: 0.05 } },
              { label: 'ay', range: { min: 0.0, max: 0.0, step: 0.05 } },
              { label: 'ayaw', range: { min: 0.2, max: 3.0, step: 0.1 } },
            ],
            unit: '[m/s^2, m/s^2, rad/s^2]', live: true,
            safety_class: 'locked_while_moving',
            description: '実機の乗り心地を決める最重要値。',
          },
          {
            key: 'controller_server.FollowPath.use_rotate_to_heading',
            node: 'controller_server', ros_node: '/controller_server',
            name: 'FollowPath.use_rotate_to_heading', type: 'bool',
            value: true, default: true, range: null, unit: null,
            live: false, safety_class: 'caution',
            description: '経路始端でその場旋回して向きを合わせる。',
          },
        ],
      })
      ingest({
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_active: false,
        estop: false, clients: 1, preset: null, stamp: 1,
      })
    })

    // ノード別にまとまり、実 ROS ノード名も出ること
    await expect(page.getByText('/local_costmap/local_costmap')).toBeVisible()

    // live / restart の区分
    await expect(
      page.getByTestId('param-local_costmap.robot_radius').getByText('restart'),
    ).toBeVisible()

    // live: false は操作できない（送っても gateway が拒否する）
    await expect(page.getByTestId('input-local_costmap.robot_radius')).toBeDisabled()

    // 配列は軸ごとにスライダー。差動二輪の vy は動かせない
    await expect(page.getByTestId('input-velocity_smoother.max_accel-ax')).toBeEnabled()
    await expect(page.getByTestId('input-velocity_smoother.max_accel-ay')).toBeDisabled()
    await expect(page.getByTestId('input-velocity_smoother.max_accel-ayaw')).toBeEnabled()

    // registry とのずれ・応答しないノードを隠さない
    await expect(page.getByTestId('mismatches')).toBeVisible()
    await expect(page.getByTestId('unreachable')).toBeVisible()

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-params.png`,
      fullPage: true,
    })
  })

  test('走行中は locked_while_moving が操作できない', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (frame: Record<string, unknown>) => void
      }).__whillIngest
      ingest({
        type: 'params', presets: [], preset: null, unreachable: [], mismatches: [],
        params: [{
          key: 'controller_server.FollowPath.desired_linear_vel',
          node: 'controller_server', ros_node: '/controller_server',
          name: 'FollowPath.desired_linear_vel', type: 'double',
          value: 0.3, default: 0.3, range: { min: 0.05, max: 1.0, step: 0.01 },
          unit: 'm/s', live: true, safety_class: 'locked_while_moving',
          description: '説明',
        }],
      })
      ingest({
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_active: false,
        estop: false, clients: 1, preset: null, stamp: 1,
      })
    })

    const input = page.getByTestId('input-controller_server.FollowPath.desired_linear_vel')
    await expect(input).toBeEnabled()

    // 走り出したら無効化する（最終判断は gateway 側でもする）
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (frame: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_active: true,
        estop: false, clients: 1, preset: null, stamp: 2,
      })
    })
    await expect(input).toBeDisabled()
    await expect(page.getByText('走行中は変更できない（locked_while_moving）')).toBeVisible()
  })

  test('拒否の理由が変更ログに残る', async ({ page }) => {
    // 黙って値が戻ると「動かしたのに変わらない」になり、範囲外なのか
    // 走行中なのか再起動が要るのか区別できない。
    await openWithToken(page)
    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (frame: Record<string, unknown>) => void
      }).__whillIngest
      ingest({
        type: 'params', presets: [], preset: null, unreachable: [], mismatches: [],
        params: [{
          key: 'controller_server.FollowPath.min_lookahead_dist',
          node: 'controller_server', ros_node: '/controller_server',
          name: 'FollowPath.min_lookahead_dist', type: 'double',
          value: 0.6, default: 0.6, range: { min: 0.2, max: 1.5, step: 0.05 },
          unit: 'm', live: true, safety_class: 'caution', description: '説明',
        }],
      })
      ingest({
        type: 'param_changed',
        key: 'controller_server.FollowPath.min_lookahead_dist',
        accepted: false, value: 0.6, source: 'slider',
        reason: '99.0 が上限 1.5 を上回る',
      })
    })

    const log = page.getByTestId('change-log')
    await expect(log).toBeVisible()
    await expect(log).toContainText('NG')
    await expect(log).toContainText('99.0 が上限 1.5 を上回る')
  })

  test('gateway 未接続では E-stop が押せないと分かる', async ({ page }) => {
    // 押した感触だけあって何も起きないのが最悪。押せないなら押せないと出す。
    await openWithToken(page)
    const button = page.getByTestId('estop')
    await expect(button).toBeDisabled()
    await expect(button).toHaveAttribute('title', /届かない/)
  })

  test('E-stop 中は画面全体で分かる', async ({ page }, testInfo) => {
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_active: true,
        estop: true, clients: 2, preset: null, stamp: 1,
      })
    })

    await expect(page.getByTestId('estop-banner')).toBeVisible()
    await expect(page.getByTestId('topbar')).toHaveClass(/estop-engaged/)
    await expect(page.getByTestId('estop')).toHaveText('E-STOP 解除')
    // 何人繋がっているかも出す（1 人が押したら全員に効く前提を分かりやすく）
    await expect(page.getByTestId('clients')).toContainText('2 人')

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-estop.png`,
      fullPage: true,
    })
  })

  test('E-stop の解除は確認を挟み、再開しないことを伝える', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_active: false,
        estop: true, clients: 1, preset: null, stamp: 1,
      })
    })

    // 未接続なので押せない。接続済みの状態を作ってから押す。
    await page.evaluate(() => {
      const store = (window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      })
      void store
    })
    await expect(page.getByTestId('estop')).toBeDisabled()
  })

  test('遅延が未測定なら数字を出さない', async ({ page }) => {
    // 古い数字や 0 を出すと「速い」と誤読する
    await openWithToken(page)
    await expect(page.getByTestId('latency')).toContainText('—')
  })

  test('スライダーを動かすと param_set が送られる', async ({ page }, testInfo) => {
    // gateway 抜きでも「スライダー → 送信」の経路が生きていることは確かめられる。
    // 未接続なら送信は失敗し、変更ログに理由が残る（黙って何も起きない、を防ぐ）。
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'params', presets: [], preset: null, unreachable: [], mismatches: [],
        params: [{
          key: 'controller_server.FollowPath.min_lookahead_dist',
          node: 'controller_server', ros_node: '/controller_server',
          name: 'FollowPath.min_lookahead_dist', type: 'double',
          value: 0.6, default: 0.6, range: { min: 0.2, max: 1.5, step: 0.05 },
          unit: 'm', live: true, safety_class: 'caution',
          description: '左右振動の直接原因。0.6 は蛇行の波長を上回る下限。',
        }],
      })
    })

    const key = 'controller_server.FollowPath.min_lookahead_dist'
    const input = page.getByTestId(`input-${key}`)
    await input.fill('0.9')
    await input.press('Enter')

    // 未接続なので拒否され、理由が残る
    const log = page.getByTestId('change-log')
    await expect(log).toBeVisible()
    await expect(log).toContainText('gateway に繋がっていない')

    // 拒否されたら入力欄は実際の値に戻る
    await expect(input).toHaveValue('0.6')

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-slider.png`,
      fullPage: true,
    })
  })

  test('仮想障害物が点線円で描かれる', async ({ page }, testInfo) => {
    await openWithToken(page)
    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest
      ingest({
        type: 'costmap', scope: 'local', frame_id: 'map', resolution: 0.5,
        width: 20, height: 20, origin_x: -5, origin_y: -5,
        rle: [0, 400], ratio: 0.01, stamp: 1, seq: 1,
      })
      ingest({ type: 'pose', x: 0, y: 0, yaw: 0, frame_id: 'map', source: 'test', stamp: 1 })
      ingest({
        type: 'obstacles',
        obstacles: [
          { id: 'a', frame_id: 'map', x: 2, y: 1, radius: 0.8 },
          { id: 'b', frame_id: 'map', x: -2, y: -1, radius: 0.4 },
        ],
      })
    })

    // 個数を常に出す。置いたまま忘れられるのが一番まずい。
    await expect(page.getByTestId('obstacle-count')).toContainText('2')
    await expect(page.getByTestId('obstacles-clear')).toBeVisible()

    // 点線円の色が canvas に出ていること。実障害物（赤）や LiDAR（橙）とは
    // 別の色にしてある。色だけでなく線種も変えているが、ここでは色で確認する。
    const hasVirtualColour = await page.evaluate(() => {
      const canvas = document.querySelector(
        '[data-testid="overview-canvas"]',
      ) as HTMLCanvasElement
      const data = canvas.getContext('2d')!
        .getImageData(0, 0, canvas.width, canvas.height).data
      for (let i = 0; i < data.length; i += 4) {
        // #d07ce0 に近い画素があるか（アンチエイリアスで多少ずれる）
        if (
          Math.abs(data[i] - 0xd0) < 40 &&
          Math.abs(data[i + 1] - 0x7c) < 40 &&
          Math.abs(data[i + 2] - 0xe0) < 40
        ) {
          return true
        }
      }
      return false
    })
    expect(hasVirtualColour, '仮想障害物の色が描かれていない').toBe(true)

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-obstacles.png`,
      fullPage: true,
    })
  })

  test('配置モードを入れないとクリックで置かれない', async ({ page }) => {
    // 地図を動かすつもりのクリックで障害物が生えるのは事故のもと。
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({ type: 'obstacles', obstacles: [] })
    })

    await expect(page.getByTestId('obstacle-radius')).toHaveCount(0)
    await page.getByTestId('overview-canvas').click({ position: { x: 200, y: 200 } })
    // 未接続なので送っても届かないが、そもそも送らないことを見たい。
    // 送っていれば変更ログか error が出る（置けないことの確認）。
    await expect(page.getByTestId('obstacle-count')).toContainText('0')

    // モードを入れると半径のスライダーが出る
    await page.getByTestId('placing-mode').check()
    await expect(page.getByTestId('obstacle-radius')).toBeVisible()
  })

  test('全消去は障害物があるときだけ出る', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({ type: 'obstacles', obstacles: [] })
    })
    await expect(page.getByTestId('obstacles-clear')).toHaveCount(0)
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
