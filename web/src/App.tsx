import { TopBar } from './panels/TopBar'
import { Overview2D } from './panels/Overview2D'
import { ParamsPanel } from './panels/ParamsPanel'

/** dev レイアウト。
 *
 * Phase 3 でパネルの中身を実装する。Phase 0 の時点では、Playwright の
 * スクリーンショット取得と描画バグ検知の経路を先に通しておくために
 * レイアウトと骨格だけ置く。
 */
export function App() {
  return (
    <div className="app">
      <TopBar />
      <div className="layout">
        <Overview2D />
        <ParamsPanel />
      </div>
    </div>
  )
}
