/** gateway の購読ストリーム（#52）。
 *
 * `subscribe` は**一覧で置き換える**（足し算ではない）。画像を足すには既定の一覧に
 * 画像を加えたものを送り、外すには既定の一覧を送り直す。そのため既定の一覧を
 * web 側にも持つ。**正は gateway の `protocol.DEFAULT_STREAMS`。** 食い違いは
 * `tests/ros/test_gateway_imports.py` が検出する。
 */

export const DEFAULT_STREAMS = [
  'status',
  'params',
  'costmap',
  'pose',
  'path',
  'scan',
  'obstacles',
  'replay',
  'telemetry',
  'dispatch_state',
] as const

/** 画像は帯域を食うので既定に入れない。camera パネルを開いているあいだだけ足す。 */
export function streamsWithImage(): string[] {
  return [...DEFAULT_STREAMS, 'image']
}

export function defaultStreams(): string[] {
  return [...DEFAULT_STREAMS]
}

/** `CompressedImage.format` から MIME を決める。
 *
 * realsense の圧縮トピックは `rgb8; jpeg compressed bgr8` のような文字列を入れる。
 * png を含まなければ JPEG として扱う（image_transport の compressed の既定）。 */
export function imageMime(format: string): 'image/png' | 'image/jpeg' {
  return /png/i.test(format) ? 'image/png' : 'image/jpeg'
}
