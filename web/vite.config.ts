import { readFileSync } from 'node:fs'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/** 開発サーバを https にする（#55）。gateway / stackd と同じ環境変数を読む。
 *
 * iPad は http を https に上げてしまい、http の開発サーバを開けない。
 * **指定されているのに読めなければ起動しない**（gateway と同じ規則。平文に
 * 黙って戻ると、iPad からは原因の分からないエラーしか見えない）。 */
function httpsOptions() {
  const cert = process.env.WHILL_TLS_CERT?.trim()
  const key = process.env.WHILL_TLS_KEY?.trim()
  if (!cert && !key) return undefined
  if (!cert || !key) {
    throw new Error('WHILL_TLS_CERT と WHILL_TLS_KEY は両方指定すること')
  }
  return { cert: readFileSync(cert), key: readFileSync(key) }
}

export default defineConfig({
  plugins: [react()],
  server: {
    // 他PC / tablet から実機PC の dev サーバへ直接繋ぐ運用なので LAN に開く。
    // 公開先はあくまで LAN 内。外向きに晒さないこと (設計原則 1)。
    host: '0.0.0.0',
    port: 5173,
    https: httpsOptions(),
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
  },
})
