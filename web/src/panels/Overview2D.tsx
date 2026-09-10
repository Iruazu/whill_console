import { useEffect, useRef } from 'react'

import { cellColor, decodeRle } from '../lib/rle'
import { useConsoleStore } from '../state/store'

/** 2D 俯瞰。costmap + path + LiDAR 2D 投影 + 仮想障害物。
 *
 * Canvas で描く。3D は Foxglove / Lichtblick に委譲する（設計原則 2）ので、
 * ここで 3D を足す提案は却下すること。
 */
export function Overview2D() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const costmap = useConsoleStore((s) => s.costmap)
  const followRobot = useConsoleStore((s) => s.followRobot)
  const headingUp = useConsoleStore((s) => s.headingUp)
  const setFollowRobot = useConsoleStore((s) => s.setFollowRobot)
  const setHeadingUp = useConsoleStore((s) => s.setHeadingUp)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !costmap) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const cells = decodeRle(costmap.rle, costmap.width * costmap.height)
    const image = ctx.createImageData(costmap.width, costmap.height)
    for (let i = 0; i < cells.length; i += 1) {
      // OccupancyGrid の行は下から上。ImageData は上から下なので反転する。
      const row = costmap.height - 1 - Math.floor(i / costmap.width)
      const target = (row * costmap.width + (i % costmap.width)) * 4
      const [r, g, b, a] = cellColor(cells[i])
      image.data[target] = r
      image.data[target + 1] = g
      image.data[target + 2] = b
      image.data[target + 3] = a
    }
    ctx.putImageData(image, 0, 0)
  }, [costmap])

  return (
    <div className="panel overview" data-testid="overview2d">
      <h2>俯瞰 2D</h2>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
        <label>
          <input
            type="checkbox"
            checked={followRobot}
            onChange={(e) => setFollowRobot(e.target.checked)}
          />{' '}
          車体追従
        </label>
        <label>
          <input
            type="checkbox"
            checked={headingUp}
            onChange={(e) => setHeadingUp(e.target.checked)}
          />{' '}
          進行方向上
        </label>
      </div>
      {costmap ? (
        <canvas ref={canvasRef} width={costmap.width} height={costmap.height} />
      ) : (
        <p className="placeholder">
          costmap 未受信。gateway (Phase 2) が繋がると描画される。
        </p>
      )}
    </div>
  )
}
