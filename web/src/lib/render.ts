import { cellColor } from './rle'
import { costmapAffine, scanToWorld, worldToCanvas } from './transform'
import type { ViewState, Viewport } from './transform'
import type {
  CostmapState,
  PathFrame,
  PoseFrame,
  ScanFrame,
  VirtualObstacle,
} from './types'

/** 俯瞰図の描画。
 *
 * 3D は Foxglove / Lichtblick に委譲する（設計原則 2）。ここは 2D 俯瞰だけ。
 *
 * costmap は「格子 1 枚を素の ImageData に起こしてから拡大」する。セルごとに
 * `fillRect` を呼ぶと 200×200 = 4 万回の描画になり、2 Hz でも tablet が持たない。
 */

/** costmap を等倍の ImageData に起こす。拡大は描画時に任せる。 */
export function costmapToImageData(
  map: CostmapState,
  createImageData: (w: number, h: number) => ImageData,
): ImageData {
  const image = createImageData(map.width, map.height)
  for (let i = 0; i < map.cells.length; i += 1) {
    // OccupancyGrid の行は下から上、ImageData は上から下。反転する。
    const row = map.height - 1 - Math.floor(i / map.width)
    const target = (row * map.width + (i % map.width)) * 4
    const [r, g, b, a] = cellColor(map.cells[i])
    image.data[target] = r
    image.data[target + 1] = g
    image.data[target + 2] = b
    image.data[target + 3] = a
  }
  return image
}

export interface Scene {
  costmap: CostmapState | null
  pose: PoseFrame | null
  path: PathFrame | null
  scan: ScanFrame | null
  /** UI で置いた仮想障害物。**点線円で描く。** */
  obstacles?: VirtualObstacle[]
  /** costmap が古い（更新が途絶えている）。薄く描いて区別する。 */
  costmapStale?: boolean
}

export interface RenderOptions {
  view: ViewState
  viewport: Viewport
  /** costmap の ImageData。呼び出し側がキャッシュする（毎フレーム作らない）。 */
  costmapImage: ImageData | null
}

const COLOR_BG = '#0f1216'
const COLOR_PATH = '#5aa9e0'
const COLOR_SCAN = '#e0b64a'
const COLOR_ROBOT = '#4ec9a0'
const COLOR_GRID = '#1c2027'
const COLOR_VIRTUAL = '#d07ce0'
/** 仮想障害物の色。costmap の赤（実障害物）とも LiDAR の橙とも変える。
 *
 * 「センサが見ているもの」と「人が置いたもの」を取り違えると、
 * 実際には無い障害物を避けて走っている、という誤解が生まれる。
 */

export function renderScene(
  ctx: CanvasRenderingContext2D,
  scene: Scene,
  options: RenderOptions,
): void {
  const { view, viewport } = options
  ctx.save()
  ctx.fillStyle = COLOR_BG
  ctx.fillRect(0, 0, viewport.width, viewport.height)

  drawGrid(ctx, view, viewport)
  if (scene.costmap && options.costmapImage) {
    drawCostmap(ctx, scene.costmap, options.costmapImage, view, viewport,
                scene.costmapStale === true)
  }
  if (scene.obstacles?.length) {
    drawVirtualObstacles(ctx, scene.obstacles, view, viewport)
  }
  if (scene.path) drawPath(ctx, scene.path, view, viewport)
  if (scene.scan) drawScan(ctx, scene.scan, scene.pose, view, viewport)
  if (scene.pose) drawRobot(ctx, scene.pose, view, viewport)
  ctx.restore()
}

/** 1 m ごとの薄い格子。縮尺の手がかりが無いと、どれだけズームしているか
 *  分からなくなる。 */
function drawGrid(ctx: CanvasRenderingContext2D, view: ViewState, viewport: Viewport): void {
  // ズームアウトしすぎたら間隔を広げる（線で埋まると背景が読めない）
  let stepM = 1
  while (stepM * view.pixelsPerMeter < 24) stepM *= 5

  ctx.strokeStyle = COLOR_GRID
  ctx.lineWidth = 1
  const halfW = viewport.width / 2 / view.pixelsPerMeter
  const halfH = viewport.height / 2 / view.pixelsPerMeter
  const reach = Math.hypot(halfW, halfH) + stepM

  ctx.beginPath()
  for (let d = -reach; d <= reach; d += stepM) {
    const x = Math.round((view.centerX + d) / stepM) * stepM
    const a = worldToCanvas(x, view.centerY - reach, view, viewport)
    const b = worldToCanvas(x, view.centerY + reach, view, viewport)
    ctx.moveTo(a.x, a.y)
    ctx.lineTo(b.x, b.y)

    const y = Math.round((view.centerY + d) / stepM) * stepM
    const c = worldToCanvas(view.centerX - reach, y, view, viewport)
    const e = worldToCanvas(view.centerX + reach, y, view, viewport)
    ctx.moveTo(c.x, c.y)
    ctx.lineTo(e.x, e.y)
  }
  ctx.stroke()
}

function drawCostmap(
  ctx: CanvasRenderingContext2D,
  map: CostmapState,
  image: ImageData,
  view: ViewState,
  viewport: Viewport,
  stale: boolean,
): void {
  // ImageData は変換行列を無視するので、一度 canvas に載せてから drawImage する
  const buffer = imageToCanvas(image)
  if (!buffer) return

  // 置き方は transform.ts の costmapAffine に 1 か所だけ持つ。回転の向きを
  // ここで別に書くと、進行方向上で地図だけ逆に回る（実際にそうなっていた）。
  const [a, b, c, d, e, f] = costmapAffine(map, view, viewport)

  ctx.save()
  // 更新が途絶えた地図は薄くする。最新のように見せない。
  ctx.globalAlpha = stale ? 0.35 : 1
  ctx.transform(a, b, c, d, e, f)
  // 拡大時にセルが滲むと「どこが障害物か」が曖昧になる
  ctx.imageSmoothingEnabled = false
  ctx.drawImage(buffer, 0, 0)
  ctx.restore()
}

/** 仮想障害物を点線円で描く。
 *
 * **実障害物と塗り分けるだけでなく、線種も変える。** 色だけだと、色覚特性や
 * 屋外の明るいタブレットで区別が付かなくなる。点線なら形で分かる。
 */
function drawVirtualObstacles(
  ctx: CanvasRenderingContext2D,
  obstacles: VirtualObstacle[],
  view: ViewState,
  viewport: Viewport,
): void {
  ctx.save()
  ctx.strokeStyle = COLOR_VIRTUAL
  ctx.fillStyle = COLOR_VIRTUAL
  ctx.lineWidth = 2
  ctx.setLineDash([6, 4])

  for (const obstacle of obstacles) {
    const center = worldToCanvas(obstacle.x, obstacle.y, view, viewport)
    const radius = obstacle.radius * view.pixelsPerMeter
    ctx.beginPath()
    ctx.arc(center.x, center.y, radius, 0, Math.PI * 2)
    ctx.stroke()

    // 中心に点。半径が画面上で小さいと円が潰れて見えなくなる。
    ctx.beginPath()
    ctx.arc(center.x, center.y, 2, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

function drawPath(
  ctx: CanvasRenderingContext2D,
  path: PathFrame,
  view: ViewState,
  viewport: Viewport,
): void {
  if (path.points.length < 2) return
  ctx.strokeStyle = COLOR_PATH
  ctx.lineWidth = 2
  ctx.beginPath()
  path.points.forEach((point, index) => {
    const p = worldToCanvas(point.x, point.y, view, viewport)
    if (index === 0) ctx.moveTo(p.x, p.y)
    else ctx.lineTo(p.x, p.y)
  })
  ctx.stroke()
}

function drawScan(
  ctx: CanvasRenderingContext2D,
  scan: ScanFrame,
  pose: PoseFrame | null,
  view: ViewState,
  viewport: Viewport,
): void {
  const points = scanToWorld(scan, pose)
  if (points.length === 0) return
  ctx.fillStyle = COLOR_SCAN
  const size = Math.max(1, Math.min(3, view.pixelsPerMeter / 10))
  for (const point of points) {
    const p = worldToCanvas(point.x, point.y, view, viewport)
    ctx.fillRect(p.x - size / 2, p.y - size / 2, size, size)
  }
}

/** 車体を向き付きの三角で描く。丸だと向きが分からず、
 *  「進行方向上」に切り替えたときに正しいか確認できない。 */
function drawRobot(
  ctx: CanvasRenderingContext2D,
  pose: PoseFrame,
  view: ViewState,
  viewport: Viewport,
): void {
  const center = worldToCanvas(pose.x, pose.y, view, viewport)
  // 実寸で描く。WHILL は約 1.0 × 0.6 m。
  const length = 1.0 * view.pixelsPerMeter
  const width = 0.6 * view.pixelsPerMeter
  const heading = pose.yaw - view.rotation

  ctx.save()
  ctx.translate(center.x, center.y)
  // canvas の y は下向きなので、world の反時計回りは画面では時計回り
  ctx.rotate(-heading)
  ctx.fillStyle = COLOR_ROBOT
  ctx.beginPath()
  ctx.moveTo(length / 2, 0)
  ctx.lineTo(-length / 2, width / 2)
  ctx.lineTo(-length / 2, -width / 2)
  ctx.closePath()
  ctx.fill()
  ctx.restore()
}

/** ImageData を drawImage できる形にする。
 *
 * OffscreenCanvas が無い環境（古い Safari 等）では通常の canvas に退避する。
 */
function imageToCanvas(image: ImageData): CanvasImageSource | null {
  if (typeof OffscreenCanvas !== 'undefined') {
    const off = new OffscreenCanvas(image.width, image.height)
    const ctx = off.getContext('2d')
    if (!ctx) return null
    ctx.putImageData(image, 0, 0)
    return off as unknown as CanvasImageSource
  }
  const canvas = document.createElement('canvas')
  canvas.width = image.width
  canvas.height = image.height
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.putImageData(image, 0, 0)
  return canvas
}
