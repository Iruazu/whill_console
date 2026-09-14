/** gateway のトークンの保管。
 *
 * ## なぜ localStorage か
 *
 * 選択肢は 3 つあった:
 *
 *   1. URL のクエリ文字列 … **却下。** 履歴・プロキシログ・Referer に残る
 *   2. ビルド時の環境変数 … **却下。** ビルド成果物に焼き込まれ、
 *      トークンを変えるたびに再ビルドが要る
 *   3. localStorage + 初回入力 … これを採る
 *
 * LAN 限定・研究室内での運用が前提で、これ以上の防御は無い（ADR-0001 と
 * 同じ割り切り）。共有 PC で使うなら、使い終わりに「トークンを消す」ことが
 * できるよう `clearToken` を用意してある。
 */

const STORAGE_KEY = 'whill.gateway.token'

export function loadToken(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    // プライベートモード等で localStorage が使えないことがある。
    // その場合は毎回入力してもらう（動かなくなるよりまし）。
    return ''
  }
}

export function saveToken(token: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, token)
  } catch {
    // 保存できなくても接続自体はできる。黙って続ける。
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 消せなくても実害は無い
  }
}

/** gateway が受け付けるトークンの最短長。gateway / stackd の起動時の検査と揃える。 */
export const MIN_TOKEN_LENGTH = 8

/** 入力されたトークンを整える（#58）。
 *
 * tablet で 32 文字の 16 進を打つので、打ち間違いは普通に起きる。
 * 送る前に分かるものはその場で言う。前後の空白（コピーで混ざりやすい）と、
 * 途中の空白（4 文字ずつ区切って読んだものをそのまま打った場合）は落とす。
 */
export function normalizeToken(raw: string): { token: string; error: string | null } {
  const token = raw.replace(/\s+/g, '')
  if (!token) return { token, error: 'トークンを入れること' }
  if (token.length < MIN_TOKEN_LENGTH) {
    return {
      token,
      error: `短すぎる（${token.length} 文字）。gateway のトークンは ${MIN_TOKEN_LENGTH} 文字以上`,
    }
  }
  return { token, error: null }
}
