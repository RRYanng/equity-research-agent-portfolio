import type { MemoData } from '../types'
import { ratingClass } from '../ui'

export default function DecisionBar({ memo }: { memo: MemoData }) {
  const d = memo.decision
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-2xl font-semibold tracking-tight">{memo.ticker}</span>
        {d && <span className={`rounded-md px-2.5 py-1 text-sm font-medium ${ratingClass(d.rating)}`}>{d.rating}</span>}
        {d && (
          <span className={d.low_confidence
            ? 'rounded bg-amber-100 px-2 py-0.5 text-sm font-medium text-amber-800'
            : 'text-sm text-stone-500'}>
            置信度 {d.confidence}{d.low_confidence ? ' ⚠️ 低置信' : ''}
          </span>
        )}
        <span className="ml-auto text-xs text-stone-400">
          tier: {memo.tier} · {memo.as_of?.slice(0, 10)}
        </span>
      </div>
      {d && <p className="mt-3 text-[15px] leading-relaxed text-stone-800">{d.one_liner}</p>}
      {d?.rating_basis && <p className="mt-2 text-xs leading-relaxed text-stone-500">依据：{d.rating_basis}</p>}
    </div>
  )
}
