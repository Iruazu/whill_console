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
