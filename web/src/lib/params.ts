/** パラメータのキーの決まりごと。
 *
 * `config/params.yaml` の `node` がそのままキーの頭になる（`camera.rgb_camera.exposure`）。
 * カメラのノード名は実ドライバ（realsense2_camera）に合わせて `camera`（#53）。
 */

export const CAMERA_PARAM_PREFIX = 'camera.'

/** 画像の配信レート（gateway のレート制限）。camera パネルからここへ飛ばす。 */
export const IMAGE_RATE_PARAM = 'whill_gateway.image_publish_rate'
