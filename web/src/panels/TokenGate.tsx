import { useState } from 'react'

import { saveToken } from '../lib/token'

/** トークンが未設定のときに入力させる。
 *
 * gateway は無認証では起動しないので、トークンが無ければ何も見えない。
 * 「繋がらない」とだけ出して放置すると、原因（未設定）に辿り着けない。
 */
export function TokenGate({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState('')

  return (
    <div className="token-gate" data-testid="token-gate">
      <h2>gateway のトークン</h2>
      <p className="placeholder">
        実機PC で <code>WHILL_GATEWAY_TOKEN</code> に設定した値を入れる。
        ブラウザの localStorage に保存され、URL には載らない。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          const token = value.trim()
          if (!token) return
          saveToken(token)
          onSubmit(token)
        }}
      >
        <input
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="トークン"
          data-testid="token-input"
          autoFocus
        />
        <button type="submit" data-testid="token-submit">
          接続
        </button>
      </form>
    </div>
  )
}
