import { useConsoleStore } from '../state/store'

/** パラメータ操作。ノード別グループ、live / locked / restart の区分表示。
 *
 * 表示するパラメータは gateway が ParameterDescriptor を introspection して
 * 送ってくるもの。ここで一覧をハードコードしないこと（設計原則 6）。
 */
export function ParamsPanel() {
  const params = useConsoleStore((s) => s.params)

  const byNode = params.reduce<Record<string, typeof params>>((acc, spec) => {
    ;(acc[spec.node] ??= []).push(spec)
    return acc
  }, {})

  return (
    <div className="panel params" data-testid="params">
      <h2>パラメータ</h2>
      {params.length === 0 ? (
        <p className="placeholder">
          registry 未受信。gateway (Phase 2) が ParameterDescriptor を
          introspection して送ってくると、ここにスライダーが自動生成される。
        </p>
      ) : (
        Object.entries(byNode).map(([node, specs]) => (
          <section key={node}>
            <h3>{node}</h3>
            <ul>
              {specs.map((spec) => (
                <li key={spec.key}>
                  {spec.name} = {String(spec.value)} {spec.unit ?? ''}{' '}
                  <span className="badge">
                    {spec.live ? 'live' : 'restart'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}
