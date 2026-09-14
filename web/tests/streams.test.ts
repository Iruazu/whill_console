import { describe, expect, it } from 'vitest'

import { DEFAULT_STREAMS, defaultStreams, imageMime, streamsWithImage } from '../src/lib/streams'

describe('購読の一覧（#52）', () => {
  it('画像は既定に入れず、足したときだけ入る', () => {
    // 見ていないのに画像を流し続けない
    expect(defaultStreams()).not.toContain('image')
    expect(streamsWithImage()).toContain('image')
  })

  it('画像を足しても既定のものは落とさない', () => {
    // subscribe は一覧の置き換え。何かが抜けるとテレメトリや配車が黙って止まる
    for (const stream of DEFAULT_STREAMS) {
      expect(streamsWithImage()).toContain(stream)
    }
  })
})

describe('画像の MIME', () => {
  it('realsense の圧縮トピックの書式は JPEG', () => {
    expect(imageMime('rgb8; jpeg compressed bgr8')).toBe('image/jpeg')
    expect(imageMime('jpeg')).toBe('image/jpeg')
  })

  it('png を含めば PNG', () => {
    expect(imageMime('bgr8; png compressed bgr8')).toBe('image/png')
  })

  it('空でも JPEG として扱う', () => {
    expect(imageMime('')).toBe('image/jpeg')
  })
})
