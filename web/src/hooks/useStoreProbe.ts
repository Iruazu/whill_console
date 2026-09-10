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
    // テストから合成フレームを流し込めるようにする。gateway を起動せずに
    // 「地図が実際に描かれるか」を確かめるため（#20 の受け入れ判定）。
    ;(window as unknown as { __whillIngest: unknown }).__whillIngest = (
      frame: Record<string, unknown>,
    ) => useConsoleStore.getState().ingest(frame)

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
        // replay 以外では null。「再生していない」ことも読めるようにする。
        replay: state.replay && {
          elapsed: state.replay.elapsed,
          total: state.replay.total,
          rate: state.replay.rate,
          playing: state.replay.playing,
          finished: state.replay.finished,
        },
        tfFrames: state.tf ? Object.keys(state.tf.parents).length : 0,
        unhandled: state.unhandledFrames,
      }
    })
  }, [])
}
