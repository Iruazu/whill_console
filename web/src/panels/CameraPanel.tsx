import { useEffect, useState } from 'react'

import { measuredHz, pushArrival } from '../lib/camera'
import { imageMime } from '../lib/streams'
import { CAMERA_PARAM_PREFIX, IMAGE_RATE_PARAM } from '../lib/params'
import { useConsoleStore } from '../state/store'

/** カメラ（#52）。dev レイアウトだけに出す。
 *
 * ## 開いているあいだだけ画像を流す
 *
 * 画像は gateway の既定のストリームに入っていない（帯域）。パネルを開いたら
 * 画像を購読に足し、閉じたら外す。**見ていないのに流し続けない。**
 *
 * ## 止まった画像を最新に見せない
 *
 * カメラが止まっても最後の 1 枚は残る。そのまま出すと「いまこう映っている」と
 * 読んでしまうので、古くなったら薄くして何秒前のものかを出す（costmap や
 * テレメトリと同じ扱い）。
 *
 * ## 設定はパラメータパネルに任せる
 *
 * 露出と解像度は `config/params.yaml` に登録してあり（#53）、パラメータパネルの
 * スライダーがそのまま効く。**ここに camera 専用のスライダーを作らない。**
 * 作ると、範囲・safety_class・変更ログ・拒否の扱いが二重実装になる。
 * ここが持つのは「そこへ辿り着く導線」だけ。
 *
 * 深度画像・点群は出さない（設計原則 2。Foxglove に委譲する）。
 */

/** これだけ新しい画像が来なければ古いとみなす。gateway は既定 1 Hz で送る。 */
export const IMAGE_STALE_MS = 3000

/** 開いてからこれだけ待っても 1 枚も来なければ、来ない理由を出す。 */
export const IMAGE_NEVER_MS = 5000

export interface CameraPanelProps {
  /** 購読を切り替える。gateway は一覧で置き換える。 */
  setImageSubscribed: (on: boolean) => void
}

export function CameraPanel({ setImageSubscribed }: CameraPanelProps) {
  const [open, setOpen] = useState(false)
  const [openedAt, setOpenedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [arrivals, setArrivals] = useState<number[]>([])
  const image = useConsoleStore((s) => s.image)
  const params = useConsoleStore((s) => s.params)
  const setParamFilter = useConsoleStore((s) => s.setParamFilter)
  const receivedAt = useConsoleStore((s) => s.receivedAt.image)
  const connection = useConsoleStore((s) => s.connection)

  // 開閉と、繋ぎ直したときに購読を送る。再接続すると gateway 側の購読は
  // 既定に戻るので、開いたままなら送り直す。
  useEffect(() => {
    if (connection !== 'connected') return
    setImageSubscribed(open)
  }, [open, connection, setImageSubscribed])

  // 閉じずに画面を離れる（レイアウト切り替えなど）ときも外す。
  useEffect(() => () => setImageSubscribed(false), [setImageSubscribed])

  // 実測レート（ADR-0007）。宣言値ではなく、実際に届いた間隔から出す。
  useEffect(() => {
    if (receivedAt === undefined) return
    setArrivals((times) => pushArrival(times, receivedAt))
  }, [receivedAt])

  // 「n 秒前」を進めるための時計。開いているあいだだけ回す。
  useEffect(() => {
    if (!open) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [open])

  const showParams = (filter: string) => {
    setParamFilter(filter)
    document
      .querySelector('[data-testid="params"]')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const age = receivedAt === undefined ? null : now - receivedAt
  const hz = measuredHz(arrivals, now)
  const stale = age !== null && age > IMAGE_STALE_MS
  const neverArrived =
    open && image === null && openedAt !== null && now - openedAt > IMAGE_NEVER_MS

  return (
    <section className="panel camera" data-testid="camera">
      <button
        type="button"
        className="camera-toggle"
        aria-expanded={open}
        data-testid="camera-toggle"
        onClick={() => {
          setOpen((v) => !v)
          setOpenedAt(Date.now())
          setNow(Date.now())
        }}
      >
        <span className="driver-caret">{open ? '▾' : '▸'}</span>
        <h2>カメラ</h2>
        {!open && <span className="muted">開くと画像を受け取る（帯域を使う）</span>}
      </button>

      {open && (
        <div className="camera-body">
          <div className="camera-links">
            {params.some((spec) => spec.key.startsWith(CAMERA_PARAM_PREFIX)) && (
              <button
                type="button"
                className="link-button"
                data-testid="camera-params-link"
                onClick={() => showParams(CAMERA_PARAM_PREFIX)}
              >
                露出・解像度の設定を出す
              </button>
            )}
            {params.some((spec) => spec.key === IMAGE_RATE_PARAM) && (
              <button
                type="button"
                className="link-button"
                data-testid="camera-rate-link"
                onClick={() => showParams(IMAGE_RATE_PARAM)}
              >
                配信レートの設定を出す
              </button>
            )}
          </div>
          {image ? (
            <figure className={`camera-frame${stale ? ' stale' : ''}`}>
              <img
                src={`data:${imageMime(image.format)};base64,${image.data}`}
                alt="カメラの最新の画像"
                data-testid="camera-image"
              />
              <figcaption data-testid="camera-age">
                {stale
                  ? `${Math.round((age ?? 0) / 1000)} 秒前の画像（更新が止まっている）`
                  : /* 実測。宣言値ではない（設定 6 Hz なのに 1 Hz、を見つけるため） */
                    `最新${hz === null ? '' : `（実測 ${hz.toFixed(1)} Hz）`}`}
              </figcaption>
            </figure>
          ) : neverArrived ? (
            <p className="muted" data-testid="camera-none">
              画像が来ていない。カメラは既定で起動しない（mock なら <code>--camera</code>）。
              ドライバパネルの realsense も確認すること。
            </p>
          ) : (
            <p className="muted" data-testid="camera-waiting">画像を待っている…</p>
          )}
        </div>
      )}
    </section>
  )
}
