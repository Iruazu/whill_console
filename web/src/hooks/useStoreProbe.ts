import { useEffect } from 'react'

import { useConsoleStore } from '../state/store'

/** dev ビルドでだけ store の要約を `window.__whill` に出す。
 *
 * Playwright と手動デバッグから「いま何が届いているか」を確かめるため。
 * 本番ビルドには含めない（`import.meta.env.DEV` で切る）。
 */
export function useStoreProbe(): void {
  useEffect(() => {
    if (!import.meta.env.DEV) return
    return useConsoleStore.subscribe((state) => {
      ;(window as unknown as { __whill: unknown }).__whill = {
        connection: state.connection,
        detail: state.connectionDetail,
        costmaps: Object.fromEntries(
          Object.entries(state.costmaps).map(([scope, map]) => [
            scope,
            map && { width: map.width, height: map.height, seq: map.seq },
          ]),
        ),
        pose: state.pose && { x: +state.pose.x.toFixed(2), y: +state.pose.y.toFixed(2) },
        pathPoints: state.path?.points.length ?? 0,
        params: state.params.length,
        mismatches: state.mismatches.length,
        unreachable: state.unreachable,
        status: state.status && {
          robotId: state.status.robotId,
          mode: state.status.mode,
          clients: state.status.clients,
        },
        tfFrames: state.tf ? Object.keys(state.tf.parents).length : 0,
        unhandled: state.unhandledFrames,
      }
    })
  }, [])
}
