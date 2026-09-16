import { describe, expect, it } from 'vitest'

import {
  COSTMAP_KINDS,
  PARAM_CHANGE_LIMIT,
  applyFrame,
  emptyFrameState,
  isStale,
} from '../src/lib/frames'
import type { FrameState } from '../src/lib/frames'

/** フレームの解釈が正しいことを、ブラウザ抜きで固める。
 *
 * ここを間違えると「繋がっているのに画面が更新されない」になる。
 * その手のバグはブラウザ越しだと切り分けに時間がかかるので、
 * reducer を純粋関数にしてここで潰す。
 */

const apply = (state: FrameState, frame: Record<string, unknown>, now = 1000) =>
  applyFrame(state, frame, now).state

const fullCostmap = (seq = 1, scope = 'local') => ({
  type: 'costmap',
  scope,
  frame_id: 'map',
  resolution: 0.05,
  width: 4,
  height: 4,
  origin_x: -1,
  origin_y: -2,
  rle: [0, 16],
  ratio: 0.125,
  decimation: 1,
  stamp: 12.5,
  seq,
})

describe('snake_case からの変換', () => {
  it('costmap の origin と frame_id を読む', () => {
    const state = apply(emptyFrameState(), fullCostmap())
    const map = state.costmaps.local!
    expect(map.originX).toBe(-1)
    expect(map.originY).toBe(-2)
    expect(map.frameId).toBe('map')
    expect(map.cells.length).toBe(16)
  })

  it('pose の frame_id と source を読む', () => {
    const state = apply(emptyFrameState(), {
      type: 'pose', x: 1.5, y: -2.5, yaw: 0.3,
      frame_id: 'map', source: 'odometry/filtered', stamp: 9,
    })
    expect(state.pose).toEqual({
      x: 1.5, y: -2.5, yaw: 0.3,
      frameId: 'map', source: 'odometry/filtered', stamp: 9,
    })
  })

  it('status の nav_state / robot_id を読む', () => {
    const state = apply(emptyFrameState(), {
      type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'active',
      nav_active: true, moving: true, estop: false, clients: 2, preset: null, stamp: 1,
    })
    expect(state.status?.robotId).toBe('cr2-01')
    expect(state.status?.navState).toBe('active')
    expect(state.status?.navActive).toBe(true)
    expect(state.status?.moving).toBe(true)
    expect(state.status?.clients).toBe(2)
  })

  it('Nav2 を起動しないモードと、応答が無いのを区別する（#67）', () => {
    const replay = apply(emptyFrameState(), {
      type: 'status', robot_id: 'cr2-01', mode: 'replay', nav_state: 'not_started',
      nav_active: false, estop: false, clients: 1, preset: null, stamp: 1,
    })
    expect(replay.status?.navState).toBe('not_started')

    const down = apply(emptyFrameState(), {
      type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'down',
      nav_active: false, estop: false, clients: 1, preset: null, stamp: 1,
    })
    expect(down.status?.navState).toBe('down')
  })

  it('知らない状態名は真偽値に倒す（古い・新しい gateway と混ざっても壊れない）', () => {
    const state = apply(emptyFrameState(), {
      type: 'status', robot_id: 'cr2-01', mode: 'mock', nav_state: 'no-such-state',
      nav_active: true, estop: false, clients: 1, preset: null, stamp: 1,
    })
    expect(state.status?.navState).toBe('active')

    const old = apply(emptyFrameState(), {
      type: 'status', robot_id: 'cr2-01', mode: 'mock',
      nav_active: false, estop: false, clients: 1, preset: null, stamp: 1,
    })
    expect(old.status?.navState).toBe('inactive')
    expect(old.status?.moving).toBe(false)
  })

  it('param spec の ros_node / safety_class を読む', () => {
    const state = apply(emptyFrameState(), {
      type: 'params',
      params: [{
        key: 'local_costmap.inflation_layer.inflation_radius',
        node: 'local_costmap',
        ros_node: '/local_costmap/local_costmap',
        name: 'inflation_layer.inflation_radius',
        type: 'double', value: 0.6, default: 0.6,
        range: { min: 0.1, max: 2.0, step: 0.05 },
        unit: 'm', live: true, safety_class: 'caution',
        description: '説明',
      }],
      mismatches: [], unreachable: [], presets: ['cautious'], preset: null,
    })
    expect(state.params[0].rosNode).toBe('/local_costmap/local_costmap')
    expect(state.params[0].safetyClass).toBe('caution')
    expect(state.presets).toEqual(['cautious'])
  })

  it('path の points を {x, y} に直す', () => {
    const state = apply(emptyFrameState(), {
      type: 'path', frame_id: 'map', points: [[1, 2], [3, 4]], stamp: 1,
    })
    expect(state.path?.points).toEqual([{ x: 1, y: 2 }, { x: 3, y: 4 }])
  })
})

describe('costmap の部分更新', () => {
  it('全量を受けてから部分更新を貼る', () => {
    let state = apply(emptyFrameState(), fullCostmap())
    state = apply(state, {
      type: 'costmap_update', scope: 'local',
      x: 1, y: 1, width: 2, height: 2, rle: [100, 4], stamp: 13, seq: 1,
    })
    expect(Array.from(state.costmaps.local!.cells)).toEqual([
      0, 0, 0, 0,
      0, 100, 100, 0,
      0, 100, 100, 0,
      0, 0, 0, 0,
    ])
  })

  it('全量を持たない scope の部分更新は無視する', () => {
    // 貼る先が無い。捨てるのが正しい。
    const state = apply(emptyFrameState(), {
      type: 'costmap_update', scope: 'global',
      x: 0, y: 0, width: 1, height: 1, rle: [100, 1], stamp: 1, seq: 1,
    })
    expect(state.costmaps.global).toBeUndefined()
    expect(state.lastError).toBeNull()
  })

  it('古い seq の更新は貼らない', () => {
    let state = apply(emptyFrameState(), fullCostmap(5))
    state = apply(state, {
      type: 'costmap_update', scope: 'local',
      x: 0, y: 0, width: 1, height: 1, rle: [100, 1], stamp: 1, seq: 4,
    })
    expect(Array.from(state.costmaps.local!.cells)).toEqual(new Array(16).fill(0))
  })

  it('貼れない更新は黙って捨てずエラーとして残す', () => {
    // ずれた地図で描画を続けるより、何が起きたか分かるほうがよい
    let state = apply(emptyFrameState(), fullCostmap())
    state = apply(state, {
      type: 'costmap_update', scope: 'local',
      x: 3, y: 3, width: 2, height: 2, rle: [0, 4], stamp: 1, seq: 1,
    })
    expect(state.lastError).toMatch(/貼れない/)
  })

  it('local と global を別々に保持する', () => {
    let state = apply(emptyFrameState(), fullCostmap(1, 'local'))
    state = apply(state, fullCostmap(2, 'global'))
    expect(state.costmaps.local).toBeDefined()
    expect(state.costmaps.global).toBeDefined()
    expect(state.costmaps.global!.seq).toBe(2)
  })
})

describe('param_changed', () => {
  const withParam = () =>
    apply(emptyFrameState(), {
      type: 'params',
      params: [{
        key: 'controller_server.FollowPath.min_lookahead_dist',
        node: 'controller_server', ros_node: '/controller_server',
        name: 'FollowPath.min_lookahead_dist', type: 'double',
        value: 0.6, default: 0.6, range: { min: 0.2, max: 1.5 },
        unit: 'm', live: true, safety_class: 'caution', description: '説明',
      }],
      mismatches: [], unreachable: [], presets: [], preset: null,
    })

  it('受理された変更は表示値に反映する', () => {
    const state = apply(withParam(), {
      type: 'param_changed',
      key: 'controller_server.FollowPath.min_lookahead_dist',
      accepted: true, value: 0.75,
    })
    expect(state.params[0].value).toBe(0.75)
  })

  it('拒否された変更は表示値を動かさない', () => {
    // 動かすと「効いたように見えて効いていない」になる
    const state = apply(withParam(), {
      type: 'param_changed',
      key: 'controller_server.FollowPath.min_lookahead_dist',
      accepted: false, value: 99, reason: '上限を上回る',
    })
    expect(state.params[0].value).toBe(0.6)
  })

  it('拒否も履歴に残す', () => {
    // 受理だけ記録すると「動かしたのに変わらなかった」原因が追えない
    const state = apply(withParam(), {
      type: 'param_changed', key: 'x', accepted: false, value: 1,
      reason: '走行中は変更できない',
    })
    expect(state.paramChanges[0].accepted).toBe(false)
    expect(state.paramChanges[0].reason).toBe('走行中は変更できない')
  })

  it('履歴は新しいものが先頭', () => {
    let state = apply(withParam(), { type: 'param_changed', key: 'a', accepted: true, value: 1 })
    state = apply(state, { type: 'param_changed', key: 'b', accepted: true, value: 2 })
    expect(state.paramChanges.map((c) => c.key)).toEqual(['b', 'a'])
  })

  it('履歴は上限で打ち切る', () => {
    let state = withParam()
    for (let i = 0; i < PARAM_CHANGE_LIMIT + 20; i += 1) {
      state = apply(state, { type: 'param_changed', key: `k${i}`, accepted: true, value: i })
    }
    expect(state.paramChanges.length).toBe(PARAM_CHANGE_LIMIT)
  })
})

describe('mismatches / unreachable', () => {
  it('registry と実ノードのずれを隠さない', () => {
    const state = apply(emptyFrameState(), {
      type: 'params', params: [],
      mismatches: [{ key: 'a.b', registry: 0.3, live: 0.5 }],
      unreachable: ['/controller_server'], presets: [], preset: null,
    })
    expect(state.mismatches).toHaveLength(1)
    expect(state.unreachable).toEqual(['/controller_server'])
  })
})

describe('その他のフレーム', () => {
  it('tf の親子関係を保持する', () => {
    const state = apply(emptyFrameState(), {
      type: 'tf', parents: { base_link: 'odom', odom: 'map' }, stamp: 1,
    })
    expect(state.tf?.parents.base_link).toBe('odom')
    // 以前の形（edges を持たない gateway）でも落ちない
    expect(state.tf?.edges).toEqual([])
    expect(state.tf?.missing).toEqual([])
  })

  it('tf の辺の判定と来ていない辺を保持する（#51）', () => {
    const state = apply(emptyFrameState(), {
      type: 'tf',
      parents: { odom: 'map' },
      edges: [{ parent: 'map', child: 'odom', static: false, expected: true, source: 'localizer',
        age: 2.1, rate_hz: null, level: 'warn' }],
      roots: ['map'],
      missing: [{ parent: 'odom', child: 'base_link', kind: 'dynamic', source: 'EKF',
        actual_parent: null }],
      stamp: 1,
    })
    expect(state.tf?.edges[0].level).toBe('warn')
    expect(state.tf?.missing[0].child).toBe('base_link')
    expect(state.tf?.roots).toEqual(['map'])
  })

  it('diagnostics を保持する', () => {
    const state = apply(emptyFrameState(), {
      type: 'diagnostics',
      entries: [{ name: 'alignment', level: 1, message: '劣化' }],
      stamp: 1,
    })
    expect(state.diagnostics[0].level).toBe(1)
  })

  it('error を lastError に落とす', () => {
    const state = apply(emptyFrameState(), { type: 'error', reason: 'トークンが違う' })
    expect(state.lastError).toBe('トークンが違う')
  })

  it('hello は状態に落とさない', () => {
    const before = emptyFrameState()
    const { state, handled } = applyFrame(before, { type: 'hello' }, 1)
    expect(state).toBe(before)
    expect(handled).toBe(true)
  })

  it('未知の type は handled=false で無視する', () => {
    // gateway が新しいフレームを足しても古い UI が壊れないこと。
    // ただし「無視した」ことは呼び出し側が数えられる。
    const { state, handled } = applyFrame(emptyFrameState(), { type: 'future' }, 1)
    expect(handled).toBe(false)
    expect(state.lastError).toBeNull()
  })
})

describe('古さの判定', () => {
  it('一度も来ていないものは古い扱い', () => {
    expect(isStale(emptyFrameState().receivedAt, 'pose', 1000, 500)).toBe(true)
  })

  it('しきい値を超えたら古い', () => {
    // pose が来ていないのに最新位置として描かないため
    const state = apply(emptyFrameState(), { type: 'pose', x: 0, y: 0, yaw: 0 }, 1000)
    expect(isStale(state.receivedAt, 'pose', 1400, 500)).toBe(false)
    expect(isStale(state.receivedAt, 'pose', 1600, 500)).toBe(true)
  })

  it('全量を受けた直後の costmap は古くない', () => {
    // 部分更新だけを見ていると、全量を受けた直後に「古い」と判定して
    // 薄く描いてしまう。実際にこの不具合を踏んだ。
    const state = apply(emptyFrameState(), fullCostmap(), 1000)
    expect(isStale(state.receivedAt, COSTMAP_KINDS, 1100, 5000)).toBe(false)
  })

  it('全量も部分更新も途絶えたら古い', () => {
    const state = apply(emptyFrameState(), fullCostmap(), 1000)
    expect(isStale(state.receivedAt, COSTMAP_KINDS, 9000, 5000)).toBe(true)
  })

  it('部分更新が来ていれば全量が古くても新しい扱い', () => {
    let state = apply(emptyFrameState(), fullCostmap(), 1000)
    state = apply(state, {
      type: 'costmap_update', scope: 'local',
      x: 0, y: 0, width: 1, height: 1, rle: [50, 1], stamp: 2, seq: 1,
    }, 9000)
    expect(isStale(state.receivedAt, COSTMAP_KINDS, 9100, 5000)).toBe(false)
  })
})

describe('paramRevision', () => {
  const withParam = () =>
    apply(emptyFrameState(), {
      type: 'params', presets: [], preset: null, unreachable: [], mismatches: [],
      params: [{
        key: 'a.b', node: 'a', ros_node: '/a', name: 'b', type: 'double',
        value: 0.6, default: 0.6, range: { min: 0, max: 1 },
        unit: 'm', live: true, safety_class: 'none', description: '説明',
      }],
    })

  it('拒否でも revision が進む', () => {
    // 進まないと、拒否された入力が欄に残り続ける（実際は 0.6 なのに
    // 9.9 と表示される）。実機で踏んだ。
    const state = apply(withParam(), {
      type: 'param_changed', key: 'a.b', accepted: false, value: 0.6,
      reason: '上限を上回る',
    })
    expect(state.paramRevision['a.b']).toBe(1)
    expect(state.params[0].value).toBe(0.6)
  })

  it('受理でも revision が進む', () => {
    const state = apply(withParam(), {
      type: 'param_changed', key: 'a.b', accepted: true, value: 0.8,
    })
    expect(state.paramRevision['a.b']).toBe(1)
    expect(state.params[0].value).toBe(0.8)
  })

  it('キーごとに独立して数える', () => {
    let state = apply(withParam(), { type: 'param_changed', key: 'a.b', accepted: true, value: 1 })
    state = apply(state, { type: 'param_changed', key: 'c.d', accepted: true, value: 1 })
    expect(state.paramRevision['a.b']).toBe(1)
    expect(state.paramRevision['c.d']).toBe(1)
  })
})

describe('仮想障害物', () => {
  it('全量で置き換える', () => {
    let state = apply(emptyFrameState(), {
      type: 'obstacles',
      obstacles: [
        { id: 'a', frame_id: 'map', x: 1, y: 2, radius: 0.5 },
        { id: 'b', frame_id: 'map', x: 3, y: 4, radius: 1.0 },
      ],
    })
    expect(state.obstacles.map((o) => o.id)).toEqual(['a', 'b'])

    // 差分にすると UI と costmap の状態がずれたときに復旧できない
    state = apply(state, { type: 'obstacles', obstacles: [] })
    expect(state.obstacles).toEqual([])
  })

  it('snake_case を camelCase に直す', () => {
    const state = apply(emptyFrameState(), {
      type: 'obstacles',
      obstacles: [{ id: 'a', frame_id: 'map', x: 1.5, y: -2.5, radius: 0.75 }],
    })
    expect(state.obstacles[0]).toEqual({
      id: 'a', frameId: 'map', x: 1.5, y: -2.5, radius: 0.75,
    })
  })

  it('frame_id が無ければ map とみなす', () => {
    const state = apply(emptyFrameState(), {
      type: 'obstacles',
      obstacles: [{ id: 'a', x: 0, y: 0, radius: 0.5 }],
    })
    expect(state.obstacles[0].frameId).toBe('map')
  })
})

describe('再生位置', () => {
  const frame = (over: Record<string, unknown> = {}) => ({
    type: 'replay',
    bag: '/home/systemlab/whill_platform/bags/2026-07-31-campus',
    elapsed: 12.5,
    total: 235.08,
    rate: 1.0,
    playing: true,
    finished: false,
    stamp: 100,
    ...over,
  })

  it('replay モード以外では null のまま', () => {
    // gateway は replay 以外で送ってこない。null を 0 秒に潰すと
    // 「再生していない」と「先頭に居る」が区別できなくなる。
    expect(emptyFrameState().replay).toBeNull()
  })

  it('位置と速度を取り込む', () => {
    const state = apply(emptyFrameState(), frame())
    expect(state.replay).toEqual({
      bag: '/home/systemlab/whill_platform/bags/2026-07-31-campus',
      elapsed: 12.5,
      total: 235.08,
      rate: 1.0,
      playing: true,
      finished: false,
      stamp: 100,
    })
  })

  it('不明な値は null のまま持つ', () => {
    // metadata.yaml を読めなかったとき。0 で埋めると進捗バーが
    // 「先頭に居る」と嘘をつく。
    const state = apply(emptyFrameState(), frame({ total: null, rate: null, bag: null }))
    expect(state.replay?.total).toBeNull()
    expect(state.replay?.rate).toBeNull()
    expect(state.replay?.bag).toBeNull()
  })

  it('一時停止と再生終了を別に持つ', () => {
    const paused = apply(emptyFrameState(), frame({ playing: false }))
    expect(paused.replay).toMatchObject({ playing: false, finished: false })

    const done = apply(emptyFrameState(), frame({ playing: false, finished: true }))
    expect(done.replay).toMatchObject({ playing: false, finished: true })
  })

  it('受信時刻を記録する', () => {
    const state = apply(emptyFrameState(), frame(), 4242)
    expect(state.receivedAt.replay).toBe(4242)
  })
})

describe('ドライバのテレメトリ', () => {
  const frame = (over: Record<string, unknown> = {}) => ({
    type: 'telemetry',
    drivers: [
      {
        driver: 'whill_serial',
        expected: true,
        items: [
          {
            name: 'battery', driver: 'whill_serial',
            topic: '/whill/states/model_cr2', value: 87, unit: '%',
            widget: 'bar', level: 'ok', warn: 30, crit: 15,
            compare: 'below', description: '', age: 0.4,
          },
        ],
      },
    ],
    stamp: 12,
    ...over,
  })

  it('届く前は null', () => {
    expect(emptyFrameState().telemetry).toBeNull()
  })

  it('ドライバごとに取り込む', () => {
    const state = apply(emptyFrameState(), frame())
    expect(state.telemetry?.drivers[0]).toEqual({
      driver: 'whill_serial',
      expected: true,
      items: [
        {
          name: 'battery', driver: 'whill_serial',
          topic: '/whill/states/model_cr2', value: 87, unit: '%',
          widget: 'bar', level: 'ok', warn: 30, crit: 15,
          // 宣言に ops が無ければ false。主要テレメトリに勝手に入れない。
          compare: 'below', description: '', ops: false, age: 0.4,
        },
      ],
    })
  })

  it('値が無いものを 0 にしない', () => {
    // バッテリー 0 % と「バッテリー不明」を同じ絵にするのが一番まずい誤読
    const state = apply(emptyFrameState(), frame({
      drivers: [{
        driver: 'velodyne', expected: true,
        items: [{ name: 'scan_rate', value: null, level: 'unknown', age: null }],
      }],
    }))
    const item = state.telemetry!.drivers[0].items[0]
    expect(item.value).toBeNull()
    expect(item.age).toBeNull()
    expect(item.level).toBe('unknown')
  })

  it('未知の level を ok に倒さない', () => {
    // gateway が新しい level を足したときに「異常なのに緑」になるのが一番まずい
    const state = apply(emptyFrameState(), frame({
      drivers: [{ driver: 'x', expected: true, items: [{ name: 'a' }] }],
    }))
    expect(state.telemetry!.drivers[0].items[0].level).toBe('unknown')
  })

  it('expected を落とさない', () => {
    // 「値が無い」と「そもそも起動していない」の区別に使う
    const state = apply(emptyFrameState(), frame({
      drivers: [{ driver: 'realsense', expected: false, items: [] }],
    }))
    expect(state.telemetry!.drivers[0].expected).toBe(false)
  })

  it('受信時刻を記録する', () => {
    expect(apply(emptyFrameState(), frame(), 777).receivedAt.telemetry).toBe(777)
  })
})

describe('配車', () => {
  it('dispatch_node が居ないモードでは null のまま', () => {
    // 空のパネルを出すと「配車できない」と「配車していない」が区別できない
    expect(emptyFrameState().dispatch).toBeNull()
    expect(emptyFrameState().waypoints).toEqual([])
  })

  it('状態を camelCase で取り込む', () => {
    const state = apply(emptyFrameState(), {
      type: 'dispatch_state',
      job_id: 3, phase: 'ACTIVE', waypoint: 'east', progress: 0.42,
      queue_len: 1, aligned: true, fitness: 0.31,
    })
    expect(state.dispatch).toEqual({
      jobId: 3, phase: 'ACTIVE', waypoint: 'east', progress: 0.42,
      queueLen: 1, aligned: true, fitness: 0.31,
    })
  })

  it('走っていないことを進捗 0 % にしない', () => {
    const state = apply(emptyFrameState(), {
      type: 'dispatch_state', phase: 'IDLE', job_id: null, progress: null,
      queue_len: 0, aligned: null, fitness: null, waypoint: null,
    })
    expect(state.dispatch?.progress).toBeNull()
    expect(state.dispatch?.jobId).toBeNull()
    expect(state.dispatch?.aligned).toBeNull()
  })

  it('地点一覧を取り込む', () => {
    const state = apply(emptyFrameState(), {
      type: 'dispatch_waypoints',
      waypoints: [{ name: 'east', label: '東端', x: 7, y: 0, yaw: 0 }],
    })
    expect(state.waypoints).toEqual([
      { name: 'east', label: '東端', x: 7, y: 0, yaw: 0 },
    ])
  })

  it('label が無ければ name を使う', () => {
    // 空文字のボタンを出さない
    const state = apply(emptyFrameState(), {
      type: 'dispatch_waypoints', waypoints: [{ name: 'east' }],
    })
    expect(state.waypoints[0].label).toBe('east')
    expect(state.waypoints[0].x).toBeNull()
  })

  it('受信時刻を記録する', () => {
    const state = apply(emptyFrameState(), { type: 'dispatch_state' }, 555)
    expect(state.receivedAt.dispatch_state).toBe(555)
  })
})

describe('派生テレメトリ', () => {
  it('ドライバのカードに紛れ込ませない', () => {
    // どのセンサの話か読み違えるのを避ける
    const state = apply(emptyFrameState(), {
      type: 'telemetry',
      stamp: 1,
      drivers: [],
      derived: [{
        name: 'yaw_rate_vs_ndt', driver: 'derived', topic: '',
        value: 0.42, unit: 'deg/s', widget: 'number', level: 'ok',
        warn: 5, crit: 10, compare: 'above', description: '', age: 0.2,
      }],
    })
    expect(state.telemetry?.drivers).toEqual([])
    expect(state.telemetry?.derived).toHaveLength(1)
    expect(state.telemetry?.derived[0].name).toBe('yaw_rate_vs_ndt')
    expect(state.telemetry?.derived[0].unit).toBe('deg/s')
  })

  it('derived が無いフレームでも落ちない', () => {
    const state = apply(emptyFrameState(), { type: 'telemetry', drivers: [] })
    expect(state.telemetry?.derived).toEqual([])
  })

  it('測れていないときを 0 にしない', () => {
    // 止まっているあいだは評価できない。0 にすると「正常」に見える
    const state = apply(emptyFrameState(), {
      type: 'telemetry', drivers: [],
      derived: [{ name: 'yaw_rate_vs_ndt', value: null, level: 'unknown' }],
    })
    expect(state.telemetry?.derived[0].value).toBeNull()
    expect(state.telemetry?.derived[0].level).toBe('unknown')
  })
})

describe('カメラ画像（#52）', () => {
  it('取り込んで受信時刻を残す', () => {
    const state = apply(emptyFrameState(), {
      type: 'image', format: 'jpeg', data: 'AAAA', stamp: 12,
    }, 999)
    expect(state.image).toEqual({ format: 'jpeg', data: 'AAAA', stamp: 12 })
    expect(state.receivedAt.image).toBe(999)
  })

  it('空の画像で直前の 1 枚を消さない', () => {
    // 壊れた 1 通で画面が真っ白になるのを避ける
    let state = apply(emptyFrameState(), { type: 'image', format: 'jpeg', data: 'AAAA' })
    state = apply(state, { type: 'image', format: 'jpeg', data: '' })
    expect(state.image?.data).toBe('AAAA')
  })

  it('届く前は null', () => {
    expect(emptyFrameState().image).toBeNull()
  })
})
