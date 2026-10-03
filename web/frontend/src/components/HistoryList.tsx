import { useEffect, useState } from 'react'
import { listReports, type ReportSummary } from '../api/client'
import { ratingClass } from '../ui'

// 历史记录列表：服务端已归档的完整报告。点一条 → 回看(刷新不丢)。
// refreshKey 变化时重拉(新 run 完成后刷新)。activeId 高亮当前正在看的那条。
export default function HistoryList({ refreshKey, activeId, onSelect }:
  { refreshKey: number; activeId: number | null; onSelect: (id: number) => void }) {
  const [items, setItems] = useState<ReportSummary[]>([])
  const [err, setErr] = useState('')

  useEffect(() => {
    let alive = true
    listReports().then((r) => { if (alive) setItems(r) }).catch(() => { if (alive) setErr('历史加载失败') })
    return () => { alive = false }
  }, [refreshKey])

  if (err) return <div className="text-xs text-stone-400">{err}</div>
  if (items.length === 0) return <div className="text-xs text-stone-400">还没有历史报告。跑一支股票后会自动归档，刷新也不丢。</div>

  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-stone-500">历史记录（{items.length}）</div>
      <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
        {items.map((r) => (
          <li key={r.id}>
            <button
              onClick={() => onSelect(r.id)}
              className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-stone-50 ${
                activeId === r.id ? 'bg-stone-50' : ''}`}>
              <span className="font-semibold tracking-tight">{r.ticker}</span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] leading-none ${ratingClass(r.rating ?? '')}`}>
                {r.rating ?? '—'}
              </span>
              <span className="ml-auto text-xs text-stone-400">{r.saved_at.replace('T', ' ')}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
