import type { MemoData } from '../types'
import { SourceChip } from '../ui'

// NAV 资产净值区块：仅资产持有型(加密国库股/疑似)出现，不污染普通股。
// NAV 不是目标价——呈现"清算每股资产值 + 现价相对 NAV 溢价/折价"，缺数据如实标"数据不足"。

const big = (n: number) => {
  const a = Math.abs(n)
  if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  return `$${n.toFixed(0)}`
}
const num = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })

export default function NavSection({ memo }: { memo: MemoData }) {
  const nav = memo.nav
  if (!nav) return null

  // 疑似资产持有型但拿不到持仓 → 明确"不适用/数据不足"，绝不算
  if (!nav.applicable) {
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
        <h2 className="text-sm font-semibold tracking-tight text-amber-800">资产净值 (NAV) · 不适用</h2>
        <p className="mt-1 text-sm text-amber-700">{nav.reason ?? '无法计算 NAV'}</p>
      </section>
    )
  }

  const r = nav.result
  const pd = r?.premium_discount
  const naCalcFailed = !r || r.value == null

  return (
    <section className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-5">
      <div className="mb-1 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold tracking-tight text-stone-700">资产净值 (NAV) · 加密国库股</h2>
        <span className="text-xs text-stone-400">资产法估值 · 非目标价</span>
      </div>

      {naCalcFailed ? (
        <div className="mt-2 inline-flex items-center gap-1 rounded bg-stone-100 px-2 py-1 text-sm text-stone-500 ring-1 ring-stone-200">
          数据不足：{r?.reason ?? nav.crypto_value?.reason ?? '关键输入缺失，NAV 未计算（绝不编数字）'}
        </div>
      ) : (
        <>
          {/* 头条：NAV/share + 现价溢价/折价 */}
          <div className="mt-2 flex flex-wrap items-end gap-x-6 gap-y-1">
            <div>
              <div className="text-xs text-stone-400">每股 NAV（清算口径）</div>
              <div className="font-mono text-2xl font-semibold tabular-nums">${r!.value!.toFixed(2)}</div>
            </div>
            {typeof pd === 'number' && (
              <div>
                <div className="text-xs text-stone-400">现价相对 NAV</div>
                <div className={`font-mono text-2xl font-semibold tabular-nums ${pd > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                  {pd > 0 ? '+' : ''}{(pd * 100).toFixed(1)}% <span className="text-sm font-normal">{pd > 0 ? '溢价' : '折价'}</span>
                </div>
              </div>
            )}
            {typeof r!.current_price === 'number' && (
              <div className="text-sm text-stone-500">现价 ${r!.current_price!.toFixed(2)}</div>
            )}
          </div>

          {/* 持仓明细：每币 数量×价 + 溯源 */}
          <div className="mt-4 space-y-1 border-t border-indigo-100 pt-3 text-sm">
            {nav.holdings?.map((h) => {
              const pr = nav.coin_prices?.[h.coin]
              return (
                <div key={h.coin} className="flex flex-wrap items-center gap-x-2 text-stone-600">
                  <span className="font-medium uppercase">{h.coin}</span>
                  <span className="font-mono tabular-nums">{h.count != null ? num(h.count) : '—'}</span>
                  <span className="text-stone-400">×</span>
                  <span className="font-mono tabular-nums">{pr ? `$${num(pr.price)}` : '币价数据不足'}</span>
                  <SourceChip kind="live" />
                  <span className="text-xs text-stone-400">持仓: {h.source}（{h.as_of}）</span>
                </div>
              )
            })}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-stone-700">
              <span>加密总市值 <b className="font-mono">{big(nav.crypto_value!.value!)}</b></span>
              <span>+ 现金 <b className="font-mono">{big(r!.cash!)}</b></span>
              <span>− 债务 <b className="font-mono">{big(r!.total_debt!)}</b></span>
              <span>= 净资产 <b className="font-mono">{big(r!.net_asset_value!)}</b></span>
              <span>÷ 股数 <b className="font-mono">{num(r!.shares!)}</b></span>
              <SourceChip kind="computed" />
            </div>
          </div>

          {/* 折价类型标注 + 不是目标价 */}
          {nav.discount_notes && (
            <ul className="mt-3 list-disc space-y-0.5 border-t border-indigo-100 pl-5 pt-3 text-xs text-stone-500">
              {nav.discount_notes.map((d, i) => <li key={i}>{d}</li>)}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
