import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    // 他PC / tablet から実機PC の dev サーバへ直接繋ぐ運用なので LAN に開く。
    // 公開先はあくまで LAN 内。外向きに晒さないこと (設計原則 1)。
    host: '0.0.0.0',
    port: 5173,
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
  },
})
