/** dev / ops レイアウトの選択と、それぞれの初期値。
 *
 * **純粋関数と定数だけ置く。** React も DOM も触らないので vitest でそのまま
 * 検証できる（`localStorage` は明示的に渡す）。
 *
 * ## 切り替えをどう決めるか
 *
 * 選択肢は 3 つあった:
 *
 *   1. 画面幅で自動だけ … **却下。** デスクトップで ops を確認できず、
 *      開発中に「tablet に持っていって初めて崩れに気づく」ことになる
 *   2. URL のパスやクエリ … **却下。** ブックマークで固定できる利点はあるが、
 *      現場で URL を打ち替えるのは現実的でない
 *   3. 明示的な切り替え + 初回だけ画面幅で決める … これを採る
 *
 * 選択は localStorage に残す。**リロードで dev に戻ると、屋外で全 47 本の
 * スライダーが出てくる**（トークンと同じ考え方 — `token.ts`）。
 *
 * ## dev と ops で初期値が違う理由
 *
 * dev が map 固定なのは「地図全体の中でどこに居るか」を見たいから。
 * ops が追従・進行方向上なのは「いま前に何があるか」を見たいから。
 * **用途が違うので初期値も違う。** どちらかに寄せると片方が使いにくくなる。
 */

export type Layout = 'dev' | 'ops'

const STORAGE_KEY = 'whill.layout'

/** これ未満の幅で初めて開いたら ops で始める。
 *
 * Playwright の ops-tablet プロジェクトと同じ 768px を境にしてある。
 * ここを動かすならテスト側も一緒に動かすこと。
 */
export const OPS_MAX_WIDTH = 900

export interface LayoutDefaults {
  /** 俯瞰図が車体を追うか。 */
  followRobot: boolean
  /** 俯瞰図を進行方向上にするか（false なら map 固定）。 */
  headingUp: boolean
  /** パラメータのスライダーを出すか。現場では要らない。 */
  showParams: boolean
  /** 配車を出すか。 */
  showDispatch: boolean
  /** ドライバの全項目を出すか。false なら主要テレメトリだけ。 */
  showAllTelemetry: boolean
  /** カメラを出すか（#52）。運用中に見るものではない（#43 の主要テレメトリの考え方）。 */
  showCamera: boolean
  /** tf の木を出すか（#51）。false でも、止まっているときは一行で知らせる。 */
  showTfTree: boolean
}

export const LAYOUT_DEFAULTS: Record<Layout, LayoutDefaults> = {
  dev: {
    followRobot: false,
    headingUp: false,
    showParams: true,
    showDispatch: true,
    showAllTelemetry: true,
    showCamera: true,
    showTfTree: true,
  },
  ops: {
    followRobot: true,
    headingUp: true,
    // 現場で 47 本のスライダーは要らない。触れてしまうほうが危ない。
    showParams: false,
    showDispatch: true,
    // 電流や温度は切り分けのための数字。運用中に見るものではない。
    showAllTelemetry: false,
    showCamera: false,
    // 運用中に木は眺めない。止まったときだけ何が止まったかを出す。
    showTfTree: false,
  },
}

export function isLayout(value: unknown): value is Layout {
  return value === 'dev' || value === 'ops'
}

/** 保存された選択。無ければ画面幅から決める。
 *
 * 幅を見るのは**初回だけ。** 一度選んだら、画面を回しても勝手に変わらない。
 * 見ている最中にレイアウトが入れ替わるのは、操作の途中では危ない。
 */
export function loadLayout(width: number, storage?: Storage): Layout {
  try {
    const saved = (storage ?? window.localStorage).getItem(STORAGE_KEY)
    if (isLayout(saved)) return saved
  } catch {
    // プライベートモード等。幅で決めて続ける。
  }
  return width < OPS_MAX_WIDTH ? 'ops' : 'dev'
}

export function saveLayout(layout: Layout, storage?: Storage): void {
  try {
    ;(storage ?? window.localStorage).setItem(STORAGE_KEY, layout)
  } catch {
    // 残せなくても操作自体はできる。黙って続ける。
  }
}

/** ops の「主要テレメトリ」に出す項目か。
 *
 * **どれを主要とするかは `config/robots/cr2-base.yaml` の `ops: true` が決める。**
 * ここに名前を並べない（設計原則 3。UI に埋めると 3 台で食い違い、
 * 変えるのに再ビルドが要る）。
 */
export function opsItems<T extends { ops: boolean }>(items: T[]): T[] {
  return items.filter((item) => item.ops)
}
