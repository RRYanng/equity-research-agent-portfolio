import { useEffect, useState } from 'react'
import { listWatchlist, getWatchlistDiff } from '../api/client'
import type { WatchlistItem, WatchlistDiff } from '../types'
import { ratingClass, fmtMoney, ValueOrNA } from '../ui'
import DiffView from './DiffView'

// 关注列表：每支追踪标的的最近一次完整结论摘要 + 点开"相比上次"diff。
// 与 HistoryList 的区别：History = 每次分析的完整存档(点开回看整份报告)；
// 这里 = 追踪标的的最近结论 + 结构化 diff(不跑分析、不花钱)。
// refreshKey 变化时重拉(新 run 完成后同一标的会新增一条完整记录)。
export default function Watchlist({ refreshKey }: { refreshKey: number }) {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [err, setErr] = useState('')
  const [openTicker, setOpenTicker] = useState<string | null>(null)
  const [diff, setDiff] = useState<WatchlistDiff | null>(null)
  const [diffLoading, setDiffLoading] = useState(false)

  useEffect(() => {
    let alive = true
    listWatchlist().then((r) => { if (alive) setItems(r) }).catch(() => { if (alive) setErr('关注列表加载失败') })
    return () => { alive = false }
  }, [refreshKey])

  const toggle = (ticker: string) => {
    if (openTicker === ticker) { setOpenTicker(null); setDiff(null); return }
    setOpenTicker(ticker); setDiff(null); setDiffLoading(true)
    getWatchlistDiff(ticker)
      .then((d) => setDiff(d))
      .catch(() => setDiff({ ticker, available: false, note: '加载 diff 失败' }))
      .finally(() => setDiffLoading(false))
  }

  if (err) return <div className="text-xs text-stone-400">{err}</div>
  if (items.length === 0)
    return <div className="text-xs text-stone-400">关注列表为空。分析过的标的会自动进入追踪，刷新也不丢。</div>

  return (
    <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
      {items.map((it) => {
        const open = openTicker === it.ticker
        return (
          <li key={it.ticker}>
            <button
              onClick={() => toggle(it.ticker)}
              className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-stone-50 ${open ? 'bg-stone-50' : ''}`}>
              <span className="font-semibold tracking-tight">{it.ticker}</span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] leading-none ${ratingClass(it.rating ?? '')}`}>
                {it.rating ?? '—'}
              </span>
              {it.confidence && <span className="text-xs text-stone-400">{it.confidence}</span>}
              <span className="ml-auto flex items-center gap-3 text-xs text-stone-400">
                <span className="hidden sm:inline">锚 <ValueOrNA value={it.expected_value} format={fmtMoney} /></span>
                <span className="text-stone-300">{it.ts?.replace('T', ' ')}</span>
                <span className="text-stone-300">{open ? '▾' : '▸'}</span>
              </span>
            </button>
            {open && (
              <div className="border-t border-stone-100 bg-stone-50/40 px-3 py-2">
                {diffLoading
                  ? <div className="text-xs text-stone-400">加载中…</div>
                  : diff ? <DiffView diff={diff} /> : null}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
