import { expect, test } from '@playwright/test'

const SHOT_DIR = '../docs/screenshots'

const TOKEN_KEY = 'whill.gateway.token'

/** トークンを入れた状態でアプリを開く。
 *
 * 未設定だと TokenGate が出るので、レイアウトを見るテストでは先に入れておく。
 * gateway は起動していないので接続は失敗するが、**それでも画面は成立する**
 * ことを見たい（繋がらないと何も出ない、では現地で切り分けができない）。
 */
async function openWithToken(
  page: import('@playwright/test').Page,
  layout: 'dev' | 'ops' = 'dev',
) {
  // レイアウトは明示する。指定しないと初回は画面幅で決まり、ops-tablet
  // プロジェクト (768px) だけ別の画面を見ることになる。
  await page.addInitScript(
    ([key, value, layoutValue]) => {
      window.localStorage.setItem(key, value)
      window.localStorage.setItem('whill.layout', layoutValue)
    },
    [TOKEN_KEY, 'e2e-token-1234', layout],
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
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
        moving: false, estop: false, clients: 1, preset: null, stamp: 1,
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
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
        moving: false, estop: false, clients: 1, preset: null, stamp: 1,
      })
    })

    const input = page.getByTestId('input-controller_server.FollowPath.desired_linear_vel')
    await expect(input).toBeEnabled()

    // 走り出したら無効化する（最終判断は gateway 側でもする）
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (frame: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
        moving: true, estop: false, clients: 1, preset: null, stamp: 2,
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
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
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
        type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'inactive',
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

  test('再生バーは replay モードでのみ出る', async ({ page }, testInfo) => {
    await openWithToken(page)
    // mock / real では gateway が replay フレームを送らないので出ない。
    // 空のバーを常時出すと「再生していない」と「再生位置が 0 秒」を
    // 画面で区別できなくなる。
    await expect(page.getByTestId('replaybar')).toHaveCount(0)

    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'replay',
        bag: '/home/systemlab/whill_platform/bags/2026-07-31-campus',
        elapsed: 118.4, total: 235.08, rate: 1.0,
        playing: true, finished: false, stamp: 1,
      })
    })

    await expect(page.getByTestId('replaybar')).toBeVisible()
    await expect(page.getByTestId('replay-state')).toHaveText('再生中')
    await expect(page.getByTestId('replay-position')).toHaveText('1:58 / 3:55')
    await expect(page.getByTestId('replay-rate')).toHaveText('1.0x')
    await expect(page.getByTestId('replay-bag')).toHaveText('2026-07-31-campus')
    // 進捗が絵としても出ていること。数字だけだと進んでいるか掴みにくい。
    await expect(page.getByTestId('replay-fill')).toHaveAttribute('style', /width: 50\.\d%/)

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-replay.png`,
      fullPage: true,
    })
  })

  test('一時停止と再生終了を画面で区別する', async ({ page }) => {
    // 止まっている絵が「終わった」のか「その時刻に車体が止まっていた」のか
    // 分からないのが、この機能を作った理由そのもの。
    await openWithToken(page)
    const feed = (frame: Record<string, unknown>) =>
      page.evaluate(
        (f) =>
          (window as unknown as {
            __whillIngest: (x: Record<string, unknown>) => void
          }).__whillIngest(f),
        frame,
      )

    await feed({
      type: 'replay', bag: '/bags/x', elapsed: 30, total: 235.08,
      rate: null, playing: false, finished: false, stamp: 1,
    })
    await expect(page.getByTestId('replay-state')).toHaveText('停止中')
    // 止まっているなら速度は出さない。「停止中 1.0x」は矛盾している。
    await expect(page.getByTestId('replay-rate')).toHaveText('—')
    // 再開できる状態なのでボタンは「再開」。
    await expect(page.getByTestId('replay-toggle')).toHaveText('再開')

    await feed({
      type: 'replay', bag: '/bags/x', elapsed: 234.9, total: 235.08,
      rate: null, playing: false, finished: true, stamp: 2,
    })
    await expect(page.getByTestId('replay-state')).toHaveText('再生終了')
    // 終わった再生は再開できない。押せると「効かないボタン」になる。
    await expect(page.getByTestId('replay-toggle')).toBeDisabled()
    await expect(page.getByTestId('replay-toggle')).toHaveAttribute(
      'title', /起動し直す/)
  })

  test('全体長が不明なら進捗バーを出さない', async ({ page }) => {
    // 0 % で描くと「先頭に居る」と誤読する。metadata.yaml を読めなかった
    // ことが画面から分かるようにする。
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'replay', bag: null, elapsed: null, total: null,
        rate: null, playing: false, finished: false, stamp: 1,
      })
    })
    await expect(page.getByTestId('replay-track')).toHaveCount(0)
    await expect(page.getByTestId('replay-no-total')).toBeVisible()
    await expect(page.getByTestId('replay-position')).toHaveText('— / —')
  })

  test('配車パネルは dispatch_node が居るときだけ出る', async ({ page }, testInfo) => {
    await openWithToken(page)
    // replay など dispatch_node が居ないモードでは gateway が 1 通も送らない。
    // 空のパネルを出すと「配車できない」と「配車していない」が区別できない。
    await expect(page.getByTestId('dispatch')).toHaveCount(0)

    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest
      ingest({
        type: 'dispatch_waypoints',
        waypoints: [
          { name: 'west', label: '西端', x: -7, y: 0, yaw: 0 },
          { name: 'center', label: '中央', x: 0, y: 0, yaw: 0 },
          { name: 'east', label: '東端', x: 7, y: 0, yaw: 0 },
        ],
      })
      ingest({
        type: 'dispatch_state', phase: 'ACTIVE', job_id: 3, waypoint: 'east',
        progress: 0.42, queue_len: 1, aligned: true, fitness: 0.31,
      })
    })

    await expect(page.getByTestId('dispatch')).toBeVisible()
    await expect(page.getByTestId('dispatch-phase')).toHaveText('走行中')
    await expect(page.getByTestId('dispatch-queue')).toHaveText('待ち 1')
    await expect(page.getByTestId('dispatch-aligned')).toHaveText('自己位置 OK')
    await expect(page.getByTestId('dispatch-fitness')).toHaveText('fitness 0.310')
    await expect(page.getByTestId('dispatch-to-east')).toHaveText('東端')

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-dispatch.png`,
      fullPage: true,
    })
  })

  test('gateway 未接続では行き先を押せない', async ({ page }) => {
    // 押した感触だけあって何も起きないのが最悪。実際に送られることは
    // 実機構成の live テスト（live-dispatch.spec.ts）で見る。
    await openWithToken(page)
    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest
      ingest({ type: 'dispatch_waypoints', waypoints: [{ name: 'east', label: '東端' }] })
      ingest({ type: 'dispatch_state', phase: 'IDLE' })
    })
    const button = page.getByTestId('dispatch-to-east')
    await expect(button).toBeDisabled()
  })

  test('走っていない配車は取り消せない', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({ type: 'dispatch_state', phase: 'IDLE' })
    })
    await expect(page.getByTestId('dispatch-cancel')).toBeDisabled()
    // 走っていないので進捗も出さない（「進捗 0 %」と「まだ走っていない」は別）
    await expect(page.getByTestId('dispatch-progress')).toHaveCount(0)
  })

  test('地点が 1 つも無いことが分かる', async ({ page }) => {
    // 空のボタン列を出すと waypoints.yaml の指定ミスに気づけない
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({ type: 'dispatch_state', phase: 'IDLE' })
    })
    await expect(page.getByTestId('dispatch-no-waypoints')).toBeVisible()
  })

  test('終端の phase は次の配車まで残る', async ({ page }) => {
    // 一瞬で消すと短い job の結末を見逃す
    await openWithToken(page)
    await page.evaluate(() => {
      ;(window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest({
        type: 'dispatch_state', phase: 'ABORTED', waypoint: 'east',
        progress: 0.7, queue_len: 0,
      })
    })
    await expect(page.getByTestId('dispatch-phase')).toHaveText('中断')
    await expect(page.getByTestId('dispatch-active')).toBeVisible()
  })

  test('ブラウザが開く WebSocket は gateway と stackd だけ', async ({ page }) => {
    // 設計原則 1: ROS への口は gateway の WebSocket 1 本と ssh のみ。
    // 既存の配車 UI は rosbridge (9090) に直結していたので、移植のときに
    // それを持ち込んでいないことを機械的に確かめる。
    const urls: string[] = []
    page.on('websocket', (ws) => urls.push(ws.url()))
    await openWithToken(page)
    await expect(page.getByTestId('topbar')).toBeVisible()
    await page.waitForTimeout(1500)

    // Vite の HMR ソケットは開発サーバのもので、成果物には含まれない。
    // テスト用の開発サーバは 5174（playwright.config.ts）、手で起動するものは 5173。
    const app = urls.filter((url) => !/:517[34]\//.test(url) && !url.includes('/@vite/'))

    // 8765 = gateway（ROS への唯一の口）、8770 = stackd（起動・停止とログ。
    // ROS を喋らないので DDS も topic も通らない）。この 2 つ以外は増やさない。
    // 特に rosbridge (9090) — 既存の配車 UI が直結していた口 — を持ち込まない。
    const allowed = /:(8765|8770)\/?$/
    expect(app.every((url) => allowed.test(url)),
      `想定外の WebSocket: ${app.join(' / ')}`).toBe(true)
    expect(urls.some((url) => url.includes(':9090')),
      'rosbridge に繋いでいる').toBe(false)
  })

  /** telemetry フレームを 1 つ組む。宣言と同じ形。 */
  const telemetryFrame = (over: Record<string, unknown> = {}) => ({
    type: 'telemetry',
    stamp: 1,
    drivers: [
      {
        driver: 'whill_serial',
        expected: true,
        items: [
          {
            name: 'battery', driver: 'whill_serial',
            topic: '/whill/states/model_cr2', value: 87, unit: '%',
            widget: 'bar', level: 'ok', warn: 30, crit: 15,
            // cr2-base.yaml と揃える（battery / scan_rate / yaw_rate_vs_ndt が ops）
            compare: 'below', description: '', ops: true, age: 0.4,
          },
          {
            name: 'motor_current_left', driver: 'whill_serial',
            topic: '/whill/states/model_cr2', value: 9.2, unit: 'A',
            widget: 'number', level: 'warn', warn: 8, crit: 12,
            compare: 'above', description: '', age: 0.4,
          },
        ],
      },
      {
        driver: 'velodyne',
        expected: true,
        items: [
          {
            name: 'points_per_scan', driver: 'velodyne',
            topic: '/velodyne_points', value: null, unit: 'pts',
            widget: 'number', level: 'unknown', warn: 12000, crit: 6000,
            compare: 'below', description: '', age: null,
          },
          {
            name: 'scan_rate', driver: 'velodyne', topic: '/velodyne_points',
            value: null, unit: 'Hz', widget: 'number', level: 'unknown',
            warn: 8, crit: 5, compare: 'below', description: '', ops: true, age: null,
          },
        ],
      },
      {
        driver: 'rt_9axis',
        expected: true,
        items: [
          {
            name: 'yaw', driver: 'rt_9axis', topic: '/imu/data_rep145',
            value: 42.5, unit: 'deg', widget: 'heading', level: 'ok',
            warn: null, crit: null, compare: 'none', description: '', age: 0.1,
          },
          {
            name: 'temp', driver: 'rt_9axis', topic: '/imu/temperature',
            value: 34.03, unit: 'degC', widget: 'number', level: 'stale',
            warn: 60, crit: 75, compare: 'above', description: '', age: 12.4,
          },
        ],
      },
      {
        driver: 'realsense',
        expected: false,
        items: [
          {
            name: 'frame_rate', driver: 'realsense', topic: '/camera/x',
            value: null, unit: 'Hz', widget: 'number', level: 'unknown',
            warn: 4, crit: 2, compare: 'below', description: '', age: null,
          },
        ],
      },
    ],
    derived: [
      {
        name: 'yaw_rate_vs_ndt', driver: 'derived', topic: '',
        value: 0.42, unit: 'deg/s', widget: 'number', level: 'ok',
        warn: 5, crit: 10, compare: 'above', description: '', ops: true, age: 0.2,
      },
    ],
    ...over,
  })

  const feed = (page: import('@playwright/test').Page, frame: Record<string, unknown>) =>
    page.evaluate(
      (f) =>
        (window as unknown as {
          __whillIngest: (x: Record<string, unknown>) => void
        }).__whillIngest(f),
      frame,
    )

  test('drivers パネルが宣言どおりに出る', async ({ page }, testInfo) => {
    await openWithToken(page)
    // gateway が 1 通も送っていないうちは出さない。
    await expect(page.getByTestId('drivers')).toHaveCount(0)

    await feed(page, telemetryFrame())
    await expect(page.getByTestId('drivers')).toBeVisible()
    await expect(page.getByTestId('driver-whill_serial')).toBeVisible()

    // 畳んでいても異常は見える。開く理由に気づけないと意味が無い。
    await expect(page.getByTestId('telemetry-summary-motor_current_left')).toBeVisible()
    await expect(
      page.getByTestId('telemetry-value-summary-motor_current_left'),
    ).toHaveText('9.20 A')

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-drivers.png`,
      fullPage: true,
    })
  })

  test('閾値を超えたドライバが warning 色になる', async ({ page }) => {
    // Phase 5 の受け入れ条件そのもの。色は gateway が付けた level から引く
    // （UI 側で閾値を評価し直さない）。
    await openWithToken(page)
    await feed(page, telemetryFrame())
    await expect(page.getByTestId('driver-whill_serial')).toHaveClass(/level-warn/)

    await feed(page, telemetryFrame({
      drivers: [{
        driver: 'whill_serial', expected: true,
        items: [{ name: 'battery', value: 10, unit: '%', widget: 'bar',
                  level: 'crit', warn: 30, crit: 15, compare: 'below', age: 0.1 }],
      }],
    }))
    await expect(page.getByTestId('driver-whill_serial')).toHaveClass(/level-crit/)
  })

  test('起動していないドライバがそう分かる', async ({ page }) => {
    // 「センサが壊れた」のか「launch に入っていない」のかを切り分けるため
    await openWithToken(page)
    await feed(page, telemetryFrame())
    await expect(page.getByTestId('driver-down-velodyne')).toHaveText('起動していない')
    // 既定で起動しないものは赤くしない。起動していなくて当たり前。
    await expect(page.getByTestId('driver-off-realsense')).toHaveText('対象外')
    await expect(page.getByTestId('driver-realsense')).not.toHaveClass(/level-crit/)
  })

  test('展開すると全項目が出る', async ({ page }) => {
    await openWithToken(page)
    await feed(page, telemetryFrame())
    await expect(page.getByTestId('driver-detail-whill_serial')).toHaveCount(0)

    await page.getByTestId('driver-toggle-whill_serial').click()
    const detail = page.getByTestId('driver-detail-whill_serial')
    await expect(detail).toBeVisible()
    await expect(detail.getByTestId('telemetry-battery')).toBeVisible()
    // バッテリーは棒でも出す。数字だけだと残量の感覚が掴めない。
    await expect(detail.getByTestId('telemetry-bar-battery')).toBeVisible()
  })

  test('値が無いところを 0 で描かない', async ({ page }) => {
    // バッテリー 0 % と「バッテリー不明」を同じ絵にするのが一番まずい誤読
    await openWithToken(page)
    await feed(page, telemetryFrame())
    await page.getByTestId('driver-toggle-velodyne').click()
    await expect(page.getByTestId('telemetry-value-points_per_scan')).toHaveText('—')
    await expect(page.getByTestId('telemetry-bar-points_per_scan')).toHaveCount(0)
  })

  test('途絶えた値は残したまま古さを添える', async ({ page }) => {
    // 消すと「不明」と区別が付かず、そのままだと最新に見える
    await openWithToken(page)
    await feed(page, telemetryFrame())
    await page.getByTestId('driver-toggle-rt_9axis').click()
    const detail = page.getByTestId('driver-detail-rt_9axis')
    await expect(detail.getByTestId('telemetry-value-temp')).toHaveText('34.03 degC')
    await expect(detail.getByTestId('telemetry-age-temp')).toHaveText('12 秒前')
  })

  test('level を色だけでなく文字でも出す', async ({ page }) => {
    // 屋外のタブレットで輝度と角度に負ける。色覚の差もある。
    await openWithToken(page)
    await feed(page, telemetryFrame())
    await expect(
      page.getByTestId('driver-whill_serial').locator('.badge.level-warn'),
    ).toHaveText('注意')
  })

  test('派生テレメトリは別枠に出る', async ({ page }) => {
    // 単一のドライバに属さない。カードに紛れ込ませるとどのセンサの話か
    // 読み違える。
    await openWithToken(page)
    await feed(page, telemetryFrame())
    await expect(page.getByTestId('derived')).toBeVisible()
    const row = page.getByTestId('derived-yaw_rate_vs_ndt')
    await expect(row).toBeVisible()
    await expect(row.getByTestId('telemetry-value-yaw_rate_vs_ndt')).toHaveText('0.42 deg/s')
    // ドライバのカードの中には出ないこと
    await expect(
      page.getByTestId('driver-rt_9axis').getByTestId('telemetry-yaw_rate_vs_ndt'),
    ).toHaveCount(0)
  })

  test('localization 乖離が crit になると赤くなる', async ({ page }, testInfo) => {
    await openWithToken(page)
    await feed(page, telemetryFrame({
      derived: [{
        name: 'yaw_rate_vs_ndt', driver: 'derived', topic: '',
        value: 18.4, unit: 'deg/s', widget: 'number', level: 'crit',
        warn: 5, crit: 10, compare: 'above', description: '', age: 0.2,
      }],
    }))
    const row = page.getByTestId('derived-yaw_rate_vs_ndt')
    await expect(row).toHaveClass(/level-crit/)
    await expect(row.locator('.badge.level-crit')).toHaveText('異常')
    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-derived.png`,
      fullPage: true,
    })
  })

  test('測れていない乖離を 0 で描かない', async ({ page }) => {
    // 止まっているあいだは評価できない。0 は「正常」に見えてしまう。
    await openWithToken(page)
    await feed(page, telemetryFrame({
      derived: [{
        name: 'yaw_rate_vs_ndt', driver: 'derived', topic: '', value: null,
        unit: 'deg/s', widget: 'number', level: 'unknown', warn: 5, crit: 10,
        compare: 'above', description: '', age: null,
      }],
    }))
    await expect(
      page.getByTestId('derived-yaw_rate_vs_ndt')
        .getByTestId('telemetry-value-yaw_rate_vs_ndt'),
    ).toHaveText('—')
  })

  // ---- ops レイアウト ------------------------------------------------------

  test('ops はパラメータを出さず、配車と主要テレメトリを出す', async ({ page }, testInfo) => {
    await openWithToken(page, 'ops')
    await feed(page, telemetryFrame())
    await page.evaluate(() => {
      const ingest = (window as unknown as {
        __whillIngest: (f: Record<string, unknown>) => void
      }).__whillIngest
      ingest({
        type: 'dispatch_waypoints',
        waypoints: [
          { name: 'west', label: '西端' }, { name: 'center', label: '中央' },
          { name: 'east', label: '東端' },
        ],
      })
      ingest({ type: 'dispatch_state', phase: 'IDLE', aligned: true, fitness: 0.3 })
    })

    // 現場で 47 本のスライダーは要らない。
    await expect(page.getByTestId('params')).toHaveCount(0)
    await expect(page.getByTestId('dispatch')).toBeVisible()
    await expect(page.getByTestId('drivers')).toContainText('主要テレメトリ')

    // ops: true の 3 件だけ。電流や温度は出さない。
    await expect(page.getByTestId('ops-telemetry-battery')).toBeVisible()
    await expect(page.getByTestId('ops-telemetry-scan_rate')).toBeVisible()
    await expect(page.getByTestId('ops-telemetry-yaw_rate_vs_ndt')).toBeVisible()
    await expect(page.getByTestId('ops-telemetry-temp')).toHaveCount(0)
    await expect(page.getByTestId('ops-telemetry-motor_current_left')).toHaveCount(0)

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-ops.png`,
      fullPage: false,
    })
  })

  test('ops の主要テレメトリは設定の ops: true で決まる', async ({ page }) => {
    // UI に名前を並べていないこと。ops: true を付ければ出る。
    await openWithToken(page, 'ops')
    await feed(page, telemetryFrame({
      drivers: [{
        driver: 'whill_serial', expected: true,
        items: [
          { name: 'battery', value: 87, unit: '%', widget: 'bar', level: 'ok',
            compare: 'below', ops: true },
          { name: 'motor_current_left', value: 9.2, unit: 'A', widget: 'number',
            level: 'warn', compare: 'above', ops: true },
        ],
      }],
      derived: [{ name: 'yaw_rate_vs_ndt', value: 0.4, unit: 'deg/s',
                  widget: 'number', level: 'ok', compare: 'above', ops: true }],
    }))
    await expect(page.getByTestId('ops-telemetry-motor_current_left')).toBeVisible()
    await expect(page.getByTestId('ops-telemetry-yaw_rate_vs_ndt')).toBeVisible()
  })

  test('ops では E-stop がスクロールなしで押せる', async ({ page }) => {
    // 屋外で一番押したいもの。スクロールしないと見えない位置に置かない。
    await page.setViewportSize({ width: 768, height: 1024 })
    await openWithToken(page, 'ops')
    const estop = page.getByTestId('estop')
    await expect(estop).toBeInViewport()
    // ページ自体が縦にもスクロールしないこと（上部帯が流れていかない）。
    const overflow = await page.evaluate(
      () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
    )
    expect(overflow, '縦にはみ出していて E-stop が流れていく').toBeLessThanOrEqual(0)
  })

  test('ops は 768px で横スクロールしない', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 })
    await openWithToken(page, 'ops')
    await feed(page, telemetryFrame())
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, '横方向にはみ出している').toBeLessThanOrEqual(0)
  })

  test('ops の俯瞰図は追従・進行方向上で開く', async ({ page }) => {
    await openWithToken(page, 'ops')
    await expect(page.getByTestId('follow-robot')).toBeChecked()
    await expect(page.getByTestId('heading-up')).toBeChecked()
  })

  test('dev の俯瞰図は map 固定で開く', async ({ page }) => {
    await openWithToken(page, 'dev')
    await expect(page.getByTestId('follow-robot')).not.toBeChecked()
    await expect(page.getByTestId('heading-up')).not.toBeChecked()
  })

  test('ops では仮想障害物を置けない', async ({ page }) => {
    // 開発用の道具。現場で置けてしまうと実機の経路に効く障害物が生える。
    await openWithToken(page, 'ops')
    await expect(page.getByTestId('placing-mode')).toHaveCount(0)
    // 個数だけは出す。dev で置いたまま切り替えたことに気づけるように。
    await expect(page.getByTestId('obstacle-count')).toBeVisible()
  })

  test('切り替えが効き、リロードしても保たれる', async ({ page }) => {
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value),
      [TOKEN_KEY, 'e2e-token-1234'],
    )
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/')
    // 広い画面の初回は dev。
    await expect(page.getByTestId('params')).toBeVisible()

    await page.getByTestId('layout-toggle').click()
    await expect(page.getByTestId('params')).toHaveCount(0)
    await expect(page.getByTestId('follow-robot')).toBeChecked()

    // リロードで dev に戻ると、屋外で全スライダーが出てくる。
    await page.reload()
    await expect(page.getByTestId('params')).toHaveCount(0)
    await expect(page.getByTestId('layout-toggle')).toHaveText('dev へ')

    await page.getByTestId('layout-toggle').click()
    await expect(page.getByTestId('params')).toBeVisible()
    await expect(page.getByTestId('follow-robot')).not.toBeChecked()
  })

  // ---- トークンの入れ直し（#58） --------------------------------------------

  /** gateway と stackd の代わり。正しいトークンだけ通し、違えば gateway と同じ
   *  形の拒否（`error` / `fatal: true` / 理由）を返す。 */
  const fakeSockets = (page: import('@playwright/test').Page, good: string) =>
    page.addInitScript((goodToken) => {
      class FakeSocket {
        onopen: (() => void) | null = null
        onmessage: ((e: { data: string }) => void) | null = null
        onerror: (() => void) | null = null
        onclose: (() => void) | null = null
        readyState = 0
        constructor(public url: string) {
          setTimeout(() => {
            this.readyState = 1
            this.onopen?.()
          }, 10)
        }
        private reply(frame: unknown) {
          setTimeout(() => this.onmessage?.({ data: JSON.stringify(frame) }), 5)
        }
        send(raw: string) {
          const frame = JSON.parse(raw)
          if (frame.type !== 'auth') return
          if (frame.token === goodToken) {
            this.reply({ type: 'hello', authenticated: true, robot_id: 'cr2-01', mode: 'mock',
                         service: 'whill_stackd' })
            this.reply({ type: 'status', state: 'running', robot_id: 'cr2-01', mode: 'mock',
                         nav_state: 'active', estop: false, clients: 1, stamp: 1 })
          } else {
            this.reply({ type: 'error', reason: 'トークンが違う', fatal: true })
            setTimeout(() => { this.readyState = 3; this.onclose?.() }, 20)
          }
        }
        close() { this.readyState = 3; this.onclose?.() }
      }
      ;(window as unknown as { WebSocket: unknown }).WebSocket = FakeSocket
    }, good)

  test('拒否されたトークンは消して入力に戻し、理由を出す', async ({ page }, testInfo) => {
    await fakeSockets(page, 'correct-token-1234')
    await page.addInitScript(() => {
      // 以前に打ち間違えて保存されたトークン
      window.localStorage.setItem('whill.gateway.token', 'wrong-token-9999')
      window.localStorage.setItem('whill.layout', 'dev')
    })
    await page.goto('/')

    // 以前はここで「gateway error」のまま抜け出せなかった（iPad で実際に詰まった）
    await expect(page.getByTestId('token-gate')).toBeVisible()
    await expect(page.getByTestId('token-rejected')).toContainText('トークンが違う')
    expect(await page.evaluate(() => window.localStorage.getItem('whill.gateway.token')))
      .toBeNull()
    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-token-rejected.png`, fullPage: true })

    // その場で入れ直すと繋がる
    await page.getByTestId('token-input').fill('correct-token-1234')
    await page.getByTestId('token-submit').click()
    await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/)
    await expect(page.getByTestId('token-rejected')).toHaveCount(0)
    expect(await page.evaluate(() => window.localStorage.getItem('whill.gateway.token')))
      .toBe('correct-token-1234')
  })

  test('短すぎるトークンは送る前に言う', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('token-input').fill('abc')
    await expect(page.getByTestId('token-count')).toHaveText('3 文字')
    await page.getByTestId('token-submit').click()
    await expect(page.getByTestId('token-error')).toContainText('短すぎる')
    await expect(page.getByTestId('token-gate')).toBeVisible()
  })

  test('入力を表示に切り替えて打ち間違いを確かめられる', async ({ page }) => {
    await page.goto('/')
    const input = page.getByTestId('token-input')
    await expect(input).toHaveAttribute('type', 'password')
    await page.getByTestId('token-show').check()
    await expect(input).toHaveAttribute('type', 'text')
  })

  test('トークンを消すと確認のあと入力画面に戻る', async ({ page }) => {
    await fakeSockets(page, 'correct-token-1234')
    await page.addInitScript(() => {
      window.localStorage.setItem('whill.gateway.token', 'correct-token-1234')
      window.localStorage.setItem('whill.layout', 'dev')
    })
    await page.goto('/')
    await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/)

    await page.getByTestId('token-forget').click()
    // 消すと E-STOP も届かなくなる。いきなり消さない
    await expect(page.getByTestId('token-forget-dialog')).toContainText('E-STOP')
    await page.getByTestId('token-forget-confirm').click()

    await expect(page.getByTestId('token-gate')).toBeVisible()
    await expect(page.getByTestId('token-rejected')).toHaveCount(0)
    expect(await page.evaluate(() => window.localStorage.getItem('whill.gateway.token')))
      .toBeNull()
  })

  // ---- カメラ（#52） --------------------------------------------------------

  /** 購読したときだけ画像を送る偽の gateway。送られた subscribe を記録する。 */
  const fakeCameraGateway = (page: import('@playwright/test').Page) =>
    page.addInitScript(() => {
      // 1x1 の PNG
      const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
      const w = window as unknown as {
        __subs: string[][]; __cameraOn: boolean; WebSocket: unknown
      }
      w.__subs = []
      w.__cameraOn = true
      class FakeSocket {
        onopen: (() => void) | null = null
        onmessage: ((e: { data: string }) => void) | null = null
        onerror: (() => void) | null = null
        onclose: (() => void) | null = null
        private timer: number | null = null
        constructor(public url: string) {
          setTimeout(() => this.onopen?.(), 10)
        }
        private reply(frame: unknown) {
          this.onmessage?.({ data: JSON.stringify(frame) })
        }
        send(raw: string) {
          const frame = JSON.parse(raw)
          if (frame.type === 'auth') {
            this.reply({ type: 'hello', authenticated: true, robot_id: 'cr2-01', mode: 'mock' })
            this.reply({ type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
                         estop: false, clients: 1, stamp: 1 })
          }
          if (frame.type === 'subscribe' && this.url.includes('8765')) {
            w.__subs.push(frame.streams)
            if (this.timer) window.clearInterval(this.timer)
            this.timer = null
            if (frame.streams.includes('image')) {
              const push = () => {
                if (w.__cameraOn) {
                  this.reply({ type: 'image', format: 'png', data: PNG, stamp: Date.now() / 1000 })
                }
              }
              push()
              this.timer = window.setInterval(push, 300)
            }
          }
        }
        close() { this.onclose?.() }
      }
      w.WebSocket = FakeSocket
    })

  test('カメラは開いたときだけ購読し、閉じたら外す', async ({ page }, testInfo) => {
    await fakeCameraGateway(page)
    await openWithToken(page, 'dev')
    await expect(page.getByTestId('connection')).toHaveText(/gateway 接続/)
    // 閉じたままでは画像を購読しない（帯域）
    await expect(page.getByTestId('camera-image')).toHaveCount(0)
    expect((await page.evaluate(() => (window as any).__subs)).flat()).not.toContain('image')

    await page.getByTestId('camera-toggle').click()
    await expect(page.getByTestId('camera-image')).toBeVisible()
    await expect(page.getByTestId('camera-age')).toHaveText('最新')
    const afterOpen = await page.evaluate(() => (window as any).__subs.at(-1))
    expect(afterOpen).toContain('image')
    // 画像を足しても既定のものは落とさない
    expect(afterOpen).toContain('telemetry')
    expect(afterOpen).toContain('dispatch_state')
    await page.screenshot({ path: `${SHOT_DIR}/${testInfo.project.name}-camera.png`, fullPage: true })

    await page.getByTestId('camera-toggle').click()
    const afterClose = await page.evaluate(() => (window as any).__subs.at(-1))
    expect(afterClose).not.toContain('image')
    expect(afterClose).toContain('telemetry')
  })

  test('カメラが止まったら最後の画像を古いと分かる形で出す', async ({ page }) => {
    await fakeCameraGateway(page)
    await openWithToken(page, 'dev')
    await page.getByTestId('camera-toggle').click()
    await expect(page.getByTestId('camera-age')).toHaveText('最新')

    await page.evaluate(() => { (window as any).__cameraOn = false })
    // 3 秒で古いとみなす（IMAGE_STALE_MS）
    await expect(page.getByTestId('camera-age')).toContainText('秒前の画像', { timeout: 6000 })
  })

  test('ops にはカメラを出さない', async ({ page }) => {
    await openWithToken(page, 'ops')
    await expect(page.getByTestId('topbar')).toBeVisible()
    await expect(page.getByTestId('camera')).toHaveCount(0)
  })
})

test.describe('tf パネル（#51）', () => {
  const feed = (page: import('@playwright/test').Page, frame: Record<string, unknown>) =>
    page.evaluate(
      (f) =>
        (window as unknown as {
          __whillIngest: (x: Record<string, unknown>) => void
        }).__whillIngest(f),
      frame,
    )

  /** 代表 bag を再生して一時停止したときに gateway が実際に出した形（2026-09-14）。 */
  const tfFrame = (frozen: boolean) => {
    const dynamic = (parent: string, child: string, source: string, hz: number) => ({
      parent, child, static: false, expected: true, source,
      age: frozen ? 4.4 : 0.03, rate_hz: frozen ? null : hz, level: frozen ? 'crit' : 'ok',
    })
    const fixed = (parent: string, child: string) => ({
      parent, child, static: true, expected: child !== 'camera_link', source: '',
      age: null, rate_hz: null, level: 'static',
    })
    const edges = [
      dynamic('map', 'odom', 'scan-to-map localizer', 10),
      dynamic('odom', 'base_link', 'EKF', 30),
      fixed('base_link', 'camera_link'),
      fixed('base_link', 'imu_link'),
      fixed('base_link', 'velodyne'),
    ]
    return {
      type: 'tf',
      parents: Object.fromEntries(edges.map((e) => [e.child, e.parent])),
      edges,
      roots: ['map'],
      missing: [
        { parent: 'velodyne', child: 'camera_link', kind: 'static', source: '',
          actual_parent: 'base_link' },
        { parent: 'base_link', child: 'base_footprint', kind: 'static', source: '',
          actual_parent: null },
      ],
      stamp: 1,
    }
  }

  test('止まった辺を木と理由で出す', async ({ page }, testInfo) => {
    await openWithToken(page)
    await expect(page.getByTestId('tf')).toHaveCount(0)

    await feed(page, tfFrame(false))
    // 設定と bag の食い違いは注意（走行中の故障ではない）
    await expect(page.getByTestId('tf-level')).toHaveText('注意')
    await expect(page.getByTestId('tf-reasons')).toContainText('camera_link の親が base_link')

    await feed(page, tfFrame(true))
    await expect(page.getByTestId('tf-level')).toHaveText('異常')
    await expect(page.getByTestId('tf-reasons')).toContainText(
      'map → odom が止まっている 4.4 秒（scan-to-map localizer）')

    await page.getByTestId('tf-toggle').click()
    await expect(page.getByTestId('tf-frame-velodyne')).toBeVisible()
    await page.getByTestId('tf').screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-tf.png`,
    })
  })

  test('ops では止まったときだけ一行で出す', async ({ page }, testInfo) => {
    await openWithToken(page, 'ops')
    const healthy = tfFrame(false)
    await feed(page, { ...healthy, missing: [] })
    await expect(page.getByTestId('tf-alert')).toHaveCount(0)
    await expect(page.getByTestId('tf')).toHaveCount(0)

    await feed(page, tfFrame(true))
    await expect(page.getByTestId('tf-alert')).toContainText('map → odom が止まっている')
    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-tf-ops.png`,
      fullPage: true,
    })
  })
})

test.describe('Nav2 の状態表示（#67）', () => {
  const feed = (page: import('@playwright/test').Page, over: Record<string, unknown>) =>
    page.evaluate(
      (f) =>
        (window as unknown as {
          __whillIngest: (x: Record<string, unknown>) => void
        }).__whillIngest({
          type: 'status', robot_id: 'cr2-01', mode: 'mock', estop: false,
          clients: 1, preset: null, stamp: 1, ...f,
        }),
      over,
    )

  test('active でない理由ごとに表示が変わる', async ({ page }, testInfo) => {
    await openWithToken(page)
    const badge = page.getByTestId('nav-active')

    await feed(page, { nav_state: 'active' })
    await expect(badge).toHaveText('Nav2 動作中')
    await expect(badge).toHaveClass(/state-ok/)

    // 起動しているはずなのに応答が無い。**これが一番困る状態**なので赤
    await feed(page, { nav_state: 'down' })
    await expect(badge).toHaveText('Nav2 応答なし')
    await expect(badge).toHaveClass(/state-down/)

    // replay は Nav2 を上げない。赤くする理由が無い
    await feed(page, { mode: 'replay', nav_state: 'not_started' })
    await expect(badge).toHaveText('Nav2 起動しない')
    await expect(badge).not.toHaveClass(/state-down/)

    await feed(page, { nav_state: 'starting' })
    await expect(badge).toHaveText('Nav2 起動中')

    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-nav-state.png`,
      clip: { x: 0, y: 0, width: testInfo.project.name === 'ops-tablet' ? 768 : 900, height: 110 },
    })
  })

  test('走行中の無効化は moving で決まる（nav_active ではない）', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate(() => {
      const w = window as unknown as { __whillIngest: (f: Record<string, unknown>) => void }
      w.__whillIngest({
        type: 'params',
        params: [{
          key: 'controller_server.FollowPath.desired_linear_vel',
          node: 'controller_server.FollowPath', name: 'desired_linear_vel',
          ros_node: '/controller_server', type: 'double',
          value: 0.3, default: 0.3, range: { min: 0.05, max: 1.0, step: 0.01 },
          unit: 'm/s', live: true, safety_class: 'locked_while_moving', description: '説明',
        }],
      })
    })

    const input = page.getByTestId('input-controller_server.FollowPath.desired_linear_vel')
    // Nav2 が動作中でも、車体が止まっていれば触れる
    await feed(page, { nav_state: 'active', moving: false })
    await expect(input).toBeEnabled()

    // 手動操作で動いている（Nav2 は inactive）ときは触らせない
    await feed(page, { nav_state: 'inactive', moving: true, stamp: 2 })
    await expect(input).toBeDisabled()
  })
})

test.describe('カメラの設定への導線（#53）', () => {
  const CAMERA_PARAMS = [
    {
      key: 'camera.rgb_camera.color_profile', node: 'camera', name: 'rgb_camera.color_profile',
      ros_node: '/camera/camera', type: 'string', value: '640,480,6', default: '640,480,6',
      range: null, unit: null, live: false, safety_class: 'none',
      description: 'カラーストリームの 幅,高さ,FPS。',
    },
    {
      key: 'camera.rgb_camera.exposure', node: 'camera', name: 'rgb_camera.exposure',
      ros_node: '/camera/camera', type: 'int', value: 156, default: 156,
      range: { min: 1, max: 10000, step: 1 }, unit: 'us', live: true, safety_class: 'none',
      description: 'カラー画像の露出時間。',
    },
  ]

  test('camera パネルからパラメータに辿れる（専用スライダーは作らない）', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate((params) => {
      const w = window as unknown as { __whillIngest: (f: Record<string, unknown>) => void }
      w.__whillIngest({ type: 'params', params })
    }, CAMERA_PARAMS)

    await page.getByTestId('camera-toggle').click()
    await page.getByTestId('camera-params-link').click()

    // camera パネルの中にスライダーを作らない。出るのはパラメータパネルのほう
    await expect(page.getByTestId('camera')).not.toContainText('露出時間')
    await expect(page.getByTestId('params-filter')).toHaveValue('camera.')
    await expect(page.getByTestId('param-camera.rgb_camera.exposure')).toBeVisible()
    // live: false のものは操作できない（実機で probe を通すまで安全側）
    await expect(page.getByTestId('input-camera.rgb_camera.color_profile')).toBeDisabled()
  })

  test('カメラのパラメータがパラメータパネルに出る', async ({ page }, testInfo) => {
    await openWithToken(page)
    await page.evaluate((params) => {
      const w = window as unknown as { __whillIngest: (f: Record<string, unknown>) => void }
      w.__whillIngest({ type: 'params', params })
    }, CAMERA_PARAMS)
    await page.getByTestId('camera-toggle').click()
    await page.getByTestId('camera-params-link').click()
    await expect(page.getByTestId('param-camera.rgb_camera.exposure')).toBeVisible()
    await page.screenshot({
      path: `${SHOT_DIR}/${testInfo.project.name}-camera-params.png`,
      fullPage: true,
    })
  })

  test('カメラのパラメータが無ければ導線を出さない', async ({ page }) => {
    await openWithToken(page)
    await page.evaluate(() => {
      const w = window as unknown as { __whillIngest: (f: Record<string, unknown>) => void }
      w.__whillIngest({ type: 'params', params: [] })
    })
    await page.getByTestId('camera-toggle').click()
    await expect(page.getByTestId('camera-params-link')).toHaveCount(0)
  })
})
