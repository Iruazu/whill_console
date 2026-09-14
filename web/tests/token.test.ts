import { describe, expect, it } from 'vitest'

import { MIN_TOKEN_LENGTH, normalizeToken } from '../src/lib/token'

/** トークン入力の整形（#58）。tablet で 32 文字を打つので打ち間違いは普通に起きる。 */
describe('トークンの整形', () => {
  it('正しい 32 文字はそのまま通す', () => {
    const raw = '0123456789abcdef0123456789abcdef'
    expect(normalizeToken(raw)).toEqual({ token: raw, error: null })
  })

  it('前後と途中の空白を落とす', () => {
    // コピーで前後に空白が混ざる。4 文字ずつ区切って読んだものをそのまま打つこともある
    expect(normalizeToken('  0123 4567 89ab cdef \n').token).toBe('0123456789abcdef')
  })

  it('空なら言う', () => {
    expect(normalizeToken('   ').error).toMatch(/入れること/)
  })

  it('短すぎれば送る前に言う', () => {
    // gateway は 8 文字未満を受け付けない。送ってから拒否されるより先に分かるほうがよい
    const { error } = normalizeToken('abc')
    expect(error).toMatch(/短すぎる/)
    expect(error).toMatch(String(MIN_TOKEN_LENGTH))
  })

  it('下限ちょうどは通す', () => {
    expect(normalizeToken('a'.repeat(MIN_TOKEN_LENGTH)).error).toBeNull()
  })
})
