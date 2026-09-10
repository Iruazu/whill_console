import { useEffect, useMemo, useRef, useState } from 'react'

import { costmapToImageData, renderScene } from '../lib/render'
import { canvasToWorld, clampZoom, defaultView } from '../lib/transform'
import type { ViewState } from '../lib/transform'
import { COSTMAP_KINDS, isStale } from '../lib/frames'
import { useConsoleStore } from '../state/store'

/** 2D 俯瞰。costmap + path + 車体 + LiDAR。
 *
 * 3D は Foxglove / Lichtblick に委譲する（設計原則 2）。ここで 3D を足す提案は
 * 理由を述べて却下すること。
 *
 * 仮想障害物の描画は Phase 4。クリック位置から world 座標を求める経路
 * （`canvasToWorld`）だけ先に通してある。
 */

/** costmap がこれだけ来ていなければ「古い」。薄く描いて最新と区別する。
 *  local は 2 Hz で部分更新が来る前提なので、5 秒は明らかに異常。 */
const COSTMAP_STALE_MS = 5000

export function Overview2D() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<ViewState>(defaultView)
  const [size, setSize] = useState({ width: 800, height: 600 })

  const costmaps = useConsoleStore((s) => s.costmaps)
  const pose = useConsoleStore((s) => s.pose)
  const path = useConsoleStore((s) => s.path)
  const scan = useConsoleStore((s) => s.scan)
  const receivedAt = useConsoleStore((s) => s.receivedAt)
  const followRobot = useConsoleStore((s) => s.followRobot)
  const headingUp = useConsoleStore((s) => s.headingUp)
  const setFollowRobot = useConsoleStore((s) => s.setFollowRobot)
  const setHeadingUp = useConsoleStore((s) => s.setHeadingUp)

  // local を優先し、無ければ global。local は rolling window なので
  // 車体まわりが見たい dev では local のほうが有用。
  const costmap = costmaps.local ?? costmaps.global ?? null

  // ImageData は格子が変わったときだけ作り直す。毎フレーム作ると
  // 200x200 でも tablet が持たない。
  const costmapImage = useMemo(() => {
    if (!costmap) return null
    if (typeof document === 'undefined') return null
    const scratch = document.createElement('canvas').getContext('2d')
    if (!scratch) return null
    return costmapToImageData(costmap, (w, h) => scratch.createImageData(w, h))
  }, [costmap])

  // 追従と進行方向上。**dev の初期値は追従 OFF・map 固定**（計画書 Phase 3）。
  useEffect(() => {
    if (!pose) return
    setView((current) => {
      const next = { ...current }
      if (followRobot) {
        next.centerX = pose.x
        next.centerY = pose.y
      }
      next.rotation = headingUp ? pose.yaw - Math.PI / 2 : 0
      return next
    })
  }, [pose, followRobot, headingUp])

  // 親の大きさに追随する。固定サイズだと tablet で見切れる。
  useEffect(() => {
    const element = containerRef.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      setSize({ width: element.clientWidth, height: element.clientHeight })
    })
    observer.observe(element)
    setSize({ width: element.clientWidth, height: element.clientHeight })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.floor(size.width * dpr))
    canvas.height = Math.max(1, Math.floor(size.height * dpr))
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    renderScene(
      ctx,
      {
        costmap,
        pose,
        path,
        scan,
        // 全量と部分更新のどちらが来ても「新しい」。全量だけを受けた直後に
        // 「古い」と判定して薄く描く不具合を踏んだので両方を見る。
        costmapStale: isStale(receivedAt, COSTMAP_KINDS, Date.now(), COSTMAP_STALE_MS),
      },
      { view, viewport: size, costmapImage },
    )
  }, [costmap, costmapImage, pose, path, scan, view, size, receivedAt])

  // ---- 操作 ----------------------------------------------------------------

  const drag = useRef<{ x: number; y: number } | null>(null)

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    drag.current = { x: event.clientX, y: event.clientY }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drag.current) return
    const dx = event.clientX - drag.current.x
    const dy = event.clientY - drag.current.y
    drag.current = { x: event.clientX, y: event.clientY }
    setView((current) => {
      // 追従中に手で動かしたら追従を切る。勝手に戻ると操作できない。
      if (followRobot) setFollowRobot(false)
      const cos = Math.cos(current.rotation)
      const sin = Math.sin(current.rotation)
      const wx = -dx / current.pixelsPerMeter
      const wy = dy / current.pixelsPerMeter
      return {
        ...current,
        centerX: current.centerX + (wx * cos - wy * sin),
        centerY: current.centerY + (wx * sin + wy * cos),
      }
    })
  }

  const onPointerUp = () => {
    drag.current = null
  }

  const onWheel = (event: React.WheelEvent<HTMLCanvasElement>) => {
    setView((current) => ({
      ...current,
      pixelsPerMeter: clampZoom(
        current.pixelsPerMeter * (event.deltaY < 0 ? 1.15 : 1 / 1.15),
      ),
    }))
  }

  const onDoubleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    // Phase 4 の仮想障害物はここから座標を取る。いまは中心を合わせるだけ。
    const rect = event.currentTarget.getBoundingClientRect()
    const world = canvasToWorld(
      event.clientX - rect.left,
      event.clientY - rect.top,
      view,
      size,
    )
    setView((current) => ({ ...current, centerX: world.x, centerY: world.y }))
  }

  const hasMap = costmap !== null

  return (
    <div className="panel overview" data-testid="overview2d">
      <h2>俯瞰 2D</h2>
      <div className="overview-controls">
        <label>
          <input
            type="checkbox"
            checked={followRobot}
            onChange={(e) => setFollowRobot(e.target.checked)}
            data-testid="follow-robot"
          />{' '}
          車体追従
        </label>
        <label>
          <input
            type="checkbox"
            checked={headingUp}
            onChange={(e) => setHeadingUp(e.target.checked)}
            data-testid="heading-up"
          />{' '}
          進行方向上
        </label>
        <button type="button" onClick={() => setView(defaultView)} data-testid="reset-view">
          表示を戻す
        </button>
        <span className="scale-hint">
          {view.pixelsPerMeter.toFixed(0)} px/m
          {costmap ? ` · ${costmap.width}×${costmap.height}` : ''}
        </span>
      </div>
      <div className="overview-canvas" ref={containerRef}>
        <canvas
          ref={canvasRef}
          data-testid="overview-canvas"
          style={{ width: '100%', height: '100%', touchAction: 'none' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onWheel={onWheel}
          onDoubleClick={onDoubleClick}
        />
        {!hasMap && (
          <p className="placeholder overlay" data-testid="overview-empty">
            costmap 未受信。gateway に繋がると描画される。
          </p>
        )}
      </div>
    </div>
  )
}
