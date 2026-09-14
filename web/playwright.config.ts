import { defineConfig, devices } from '@playwright/test'

/** テスト用の開発サーバのポート。手で起動する 5173 とぶつけない。 */
const TEST_PORT = 5174

/** スクリーンショット自動取得。
 *
 * 目的は「描画バグを agent が検知できるようにする」こと（計画書 Phase 0）。
 * 人が見るためだけの機能ではないので、CI 相当のスクリプトとして単独で走る。
 * 出力は docs/screenshots/ に入り、PR に添付する。
 */
export default defineConfig({
  testDir: './tests',
  testMatch: /.*\.spec\.ts/,
  outputDir: './test-results',
  // 描画が落ち着いてから撮るための待ちが要るので、既定より少し長く取る
  timeout: 30_000,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${TEST_PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'dev-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      // ops レイアウトは Phase 5 だが、tablet 幅で崩れないことは早くから
      // 見ておきたいのでプロジェクトだけ先に作る（受け入れ条件は 768px）。
      // 実機 iPad の device 記述子は WebKit を要求する。ここで見たいのは
      // レイアウトであってエンジン差ではないので、Chromium を 768px で使う
      // (WebKit を入れると playwright install に sudo が要る)。
      name: 'ops-tablet',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 768, height: 1024 },
        hasTouch: true,
      },
    },
  ],
  webServer: {
    // **テスト用の開発サーバは、手で起動する 5173 と分けて、必ず平文にする**（#55）。
    // 手元で https の開発サーバ（WHILL_TLS_*）を動かしたままテストすると、
    // 同じ 5173 を http で待って固まった。TLS の配線は live テストと CLI で見る。
    command: `pnpm dev --port ${TEST_PORT} --strictPort`,
    url: `http://127.0.0.1:${TEST_PORT}`,
    env: { WHILL_TLS_CERT: '', WHILL_TLS_KEY: '' },
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
