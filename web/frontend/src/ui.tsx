import type { SourceKind } from './types'

export const fmtPct = (x: number | null | undefined) =>
  typeof x === 'number' ? `${(x * 100).toFixed(1)}%` : '数据不足'
export const fmtMoney = (x: number | null | undefined) =>
  typeof x === 'number' ? `$${x.toFixed(2)}` : '数据不足'

const CHIP: Record<SourceKind, { c: string; label: string; title: string }> = {
  live:     { c: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: '实时',      title: '来自实时数据源(yfinance/Finnhub/^TNX)' },
  computed: { c: 'bg-sky-50 text-sky-700 border-sky-200',             label: '工具算',     title: '确定性 Python 工具算出(DCF/比率/CAPM)，非 LLM 心算' },
  estimate: { c: 'bg-amber-50 text-amber-700 border-amber-200',       label: '估算',      title: '显式估算(Damodaran 行业/TAM/ERP 假设)' },
  llm:      { c: 'bg-stone-100 text-stone-500 border-stone-300',      label: 'LLM未核实', title: 'LLM 给的，无硬数据源核实' },
  other:    { c: 'bg-stone-100 text-stone-500 border-stone-200',      label: '其它',      title: '' },
}

export function SourceChip({ kind }: { kind: SourceKind }) {
  const m = CHIP[kind] ?? CHIP.other
  return (
    <span title={m.title}
      className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 align-middle text-[10px] leading-none ${m.c}`}>
      {m.label}
    </span>
  )
}

// 数值或"数据不足"：有真实数值 → 等宽数字；缺失 → 明确的浅灰"不适用"标注(与真值一眼可分)。
export function ValueOrNA({ value, format, reason }:
  { value: number | null | undefined; format: (n: number) => string; reason?: string }) {
  if (typeof value === 'number') {
    return <span className="font-mono tabular-nums text-stone-900">{format(value)}</span>
  }
  return (
    <span title={reason ? `不适用：${reason}` : '此项不适用/数据不足'}
      className="inline-flex items-center gap-1 rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-400 ring-1 ring-stone-200">
      <span className="text-stone-400">—</span>数据不足{reason ? `（${reason}）` : ''}
    </span>
  )
}

// 评级语义色：Buy绿 / Hold灰 / Sell红 / 数据不足灰
export function ratingClass(rating: string): string {
  if (/buy/i.test(rating)) return 'bg-emerald-600 text-white'
  if (/sell/i.test(rating)) return 'bg-red-600 text-white'
  if (/数据不足|n\/a|降级/i.test(rating)) return 'bg-stone-300 text-stone-700'
  return 'bg-stone-700 text-white' // Hold
}

// 镜头判定色：expensive偏贵(红)/cheap偏便宜(绿)/fair公允(灰)/关闭(灰)
export function verdictClass(v: string | null): string {
  if (v === 'expensive') return 'text-red-600'
  if (v === 'cheap') return 'text-emerald-600'
  if (v === 'fair') return 'text-stone-600'
  return 'text-stone-400'
}
export const verdictLabel = (v: string | null) =>
  v === 'expensive' ? '偏贵' : v === 'cheap' ? '偏便宜' : v === 'fair' ? '公允' : (v ?? '—')
