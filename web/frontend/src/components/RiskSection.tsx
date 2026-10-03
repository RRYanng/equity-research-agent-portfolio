import type { MemoData } from '../types'

export default function RiskSection({ memo }: { memo: MemoData }) {
  const r = memo.risk
  if (!r) return null
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-stone-700">风险与证伪</h2>
      {r.bear_thesis && (
        <div className="rounded-xl border border-stone-200 bg-white p-4 text-sm leading-relaxed text-stone-700">
          <div className="mb-1 text-xs text-stone-500">Bear thesis</div>{r.bear_thesis}
        </div>
      )}
      {Object.keys(r.risks_by_category).length > 0 && (
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <div className="mb-2 text-xs text-stone-500">分类风险</div>
          <dl className="space-y-1.5 text-sm leading-relaxed">
            {Object.entries(r.risks_by_category).map(([k, v]) => (
              <div key={k}><dt className="inline font-medium text-stone-800">{k}：</dt>
                <dd className="inline text-stone-600">{v}</dd></div>
            ))}
          </dl>
        </div>
      )}
      <div className="rounded-xl border border-stone-200 bg-white p-4">
        <div className="mb-2 text-xs text-stone-500">Falsifiers（哪些事件会证明逻辑错了）</div>
        <ol className="space-y-1.5 text-sm">
          {r.falsifiers.map((f, i) => {
            const fb = f.includes('确定性兜底')
            return (
              <li key={i} className={fb
                ? 'rounded border border-amber-200 bg-amber-50 p-2 text-amber-800'
                : 'text-stone-700'}>
                {i + 1}. {f}
              </li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}
