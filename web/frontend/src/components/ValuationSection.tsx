import type { MemoData } from '../types'
import { SourceChip, ValueOrNA, fmtMoney, fmtPct } from '../ui'

export default function ValuationSection({ memo }: { memo: MemoData }) {
  const v = memo.valuation, d = memo.decision
  if (!v) return null
  const probPct = (p: number | null) => (typeof p === 'number' ? `${(p * 100).toFixed(0)}%` : '—')
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-stone-700">当前价隐含预期 / 估值</h2>

      <div className="rounded-xl border border-stone-200 bg-white p-4">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-3">
          <Stat label="现价" value={v.current_price} fmt={fmtMoney} kind="live" />
          <Stat label="估值锚(概率加权)" value={d?.expected_value_per_share ?? null} fmt={fmtMoney}
            kind="computed" reason="无 DCF 情景/数据不足" />
          <Stat label="隐含永续增长" value={v.implied_perpetual_growth} fmt={fmtPct}
            hint="对比名义GDP~3%" kind="computed" reason="DCF 未运行/反推未收敛" />
          <Stat label="隐含显式CAGR" value={v.implied_explicit_cagr} fmt={fmtPct}
            hint="对比行业/公司历史" kind="computed" reason="DCF 未运行/反推未收敛" />
        </div>
        {v.implied_expectations && <p className="mt-3 text-sm leading-relaxed text-stone-700">{v.implied_expectations}</p>}
        {v.expectation_gap && <p className="mt-2 text-xs leading-relaxed text-stone-500">预期差：{v.expectation_gap}</p>}
      </div>

      {v.scenarios.length > 0 && (
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <div className="mb-2 flex items-center gap-2 text-xs text-stone-500">
            Bull / Base / Bear 三情景 <SourceChip kind="computed" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            {v.scenarios.map((s) => (
              <div key={s.name} className="rounded-lg border border-stone-100 bg-stone-50 p-3 text-center">
                <div className="text-xs text-stone-500">{s.name} · {probPct(s.prob)}</div>
                <div className="mt-1 text-lg font-semibold">
                  <ValueOrNA value={s.per_share_value} format={fmtMoney} reason="情景未算出" />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function Stat({ label, value, fmt, hint, kind, reason }:
  { label: string; value: number | null | undefined; fmt: (n: number) => string
    hint?: string; kind: 'live' | 'computed'; reason?: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-xs text-stone-500">{label} <SourceChip kind={kind} /></div>
      <div className="mt-0.5 text-lg font-semibold">
        <ValueOrNA value={value} format={fmt} reason={reason} />
      </div>
      {hint && typeof value === 'number' && <div className="text-[10px] text-stone-400">{hint}</div>}
    </div>
  )
}
