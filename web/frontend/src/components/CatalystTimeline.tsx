import type { MemoData } from '../types'

const dirClass = (d: string) =>
  d === '利好' ? 'text-emerald-600' : d === '利空' ? 'text-red-600' : 'text-stone-500'

export default function CatalystTimeline({ memo }: { memo: MemoData }) {
  if (!memo.catalysts.length) return null
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold text-stone-700">催化剂时间表</h2>
      <ul className="space-y-1.5">
        {memo.catalysts.map((c, i) => (
          <li key={i} className="flex gap-3 rounded-lg border border-stone-200 bg-white p-3 text-sm">
            <span className="w-9 shrink-0 font-mono text-xs text-stone-400">{c.horizon}</span>
            <div>
              <span className={dirClass(c.direction)}>[{c.direction}]</span> {c.event}
              {c.note && <p className="mt-0.5 text-xs leading-relaxed text-stone-500">{c.note}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
