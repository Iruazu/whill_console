import { useState } from 'react'

import { normalizeToken, saveToken } from '../lib/token'

/** トークンの入力。未設定のときと、gateway に拒否されたときに出る。
 *
 * gateway は無認証では起動しないので、トークンが無ければ何も見えない。
 * 「繋がらない」とだけ出して放置すると、原因（未設定）に辿り着けない。
 *
 * ## 拒否されたとき（#58）
 *
 * 以前は、間違ったトークンが保存されたまま拒否され続け、**画面から入れ直す
 * 手段が無かった**（iPad で実際に詰まり、プライベートブラウズで回避した）。
 * 拒否されたら保存を消してここに戻し、gateway が返した理由を出す。
 */
export function TokenGate({
  onSubmit,
  rejected = null,
}: {
  onSubmit: (token: string) => void
  /** gateway が返した拒否の理由。null なら単に未設定。 */
  rejected?: string | null
}) {
  const [value, setValue] = useState('')
  const [visible, setVisible] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const typed = value.replace(/\s+/g, '').length

  return (
    <div className="token-gate" data-testid="token-gate">
      <h2>gateway のトークン</h2>

      {rejected && (
        <p className="token-rejected" role="alert" data-testid="token-rejected">
          gateway に拒否された: <strong>{rejected}</strong>
          <br />
          保存していたトークンは消した。正しいトークンを入れ直すこと。
        </p>
      )}

      <p className="placeholder">
        実機PC で <code>WHILL_GATEWAY_TOKEN</code> に設定した値を入れる。
        ブラウザに保存され、URL には載らない。
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          const { token, error: problem } = normalizeToken(value)
          if (problem) {
            setError(problem)
            return
          }
          saveToken(token)
          onSubmit(token)
        }}
      >
        <input
          id="gateway-token"
          // 打ち間違いを目で確かめられるように表示を切り替えられる。
          // tablet で 32 文字を伏せ字のまま打つと、どこを間違えたか分からない。
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(event) => {
            setValue(event.target.value)
            setError(null)
          }}
          placeholder="トークン"
          data-testid="token-input"
          aria-describedby="gateway-token-help"
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          autoFocus
        />
        <button type="submit" data-testid="token-submit">
          接続
        </button>
      </form>

      <div className="token-help" id="gateway-token-help">
        <label>
          <input
            type="checkbox"
            checked={visible}
            onChange={(event) => setVisible(event.target.checked)}
            data-testid="token-show"
          />{' '}
          入力を表示する
        </label>
        {/* 32 文字のうち何文字打ったか。1 文字足りない、を送る前に気づける。 */}
        <span data-testid="token-count">{typed} 文字</span>
      </div>

      {error && (
        <p className="token-error" role="alert" data-testid="token-error">
          {error}
        </p>
      )}
    </div>
  )
}
