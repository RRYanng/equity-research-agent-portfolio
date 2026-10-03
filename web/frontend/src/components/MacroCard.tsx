import type { MemoData } from '../types'
import { ValueOrNA, SourceChip, fmtPct } from '../ui'

// 宏观环境卡片（FRED v2）：把三个真实指标从折叠的 Citations 表提到一张可读面板。
// 数字全来自后端 macro_stage 存好的 mv.indicators（FRED 确定性取值）；缺 → ValueOrNA 画"数据不足"。
// 复用现成 ValueOrNA / SourceChip / fmtPct，不新建判定、不碰四色映射。倒挂标记只是读后端已算好的布尔。

function Indicator({ label, value, reason, asof }:
  { label: string; value: number | null; reason?: string; asof?: string }) {
  return (
    <div>
      <div className="mb-1 text-xs text-stone-500">{label}</div>
      <div className="flex items-center gap-2">
        <ValueOrNA value={value} format={fmtPct} reason={reason} />
        {typeof value === 'number' && <SourceChip kind="live" />}
      </div>
      {asof && typeof value === 'number' && <div className="mt-1 text-[10px] text-stone-400">截至 {asof}</div>}
    </div>
  )
}

export default function MacroCard({ memo }: { memo: MemoData }) {
  const mo = memo.macro
  if (!mo) return null
  const { inflation: infl, unemployment: unemp, yield_curve: yc } = mo
  const hasSpread = typeof yc.spread === 'number'
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold tracking-tight text-stone-700">宏观环境 (FRED)</h2>
        <span className="text-xs text-stone-400">官方数据 · as_of 为数据所属期（非实时）</span>
      </div>
      <div className="grid gap-5 sm:grid-cols-3">
        <Indicator label="通胀 CPI YoY" value={infl.value} reason={infl.reason} asof={infl.as_of} />
        <Indicator label="失业率" value={unemp.value} reason={unemp.reason} asof={unemp.as_of} />
        <div>
          <div className="mb-1 text-xs text-stone-500">收益率曲线 2s10s</div>
          <div className="flex items-center gap-2">
            <ValueOrNA value={yc.spread} format={fmtPct} reason={yc.reason} />
            {hasSpread && <SourceChip kind="live" />}
          </div>
          {hasSpread && (
            <div className="mt-1">
              <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] leading-none ${
                yc.inverted
                  ? 'border-red-200 bg-red-50 text-red-700'
                  : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                {yc.inverted ? '倒挂 ⚠️（衰退信号）' : '正常（未倒挂）'}
              </span>
            </div>
          )}
          {hasSpread && yc.as_of && <div className="mt-1 text-[10px] text-stone-400">截至 {yc.as_of}</div>}
        </div>
      </div>
    </section>
  )
}
