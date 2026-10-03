import type { MemoData, QualityMetric, QualityTrend } from '../types'
import { ValueOrNA, SourceChip, fmtPct } from '../ui'

// 公司质量卡片(第一层)：盈利能力 / 成长趋势 / 财务健康。
// 所有数字来自 proto.quality 纯函数；缺数据 → ValueOrNA 显示"数据不足"，绝不编数字。

const mult = (n: number) => `${n.toFixed(2)}x`
// 大额金额紧凑显示：$35.9B / $512.0M
const bigMoney = (n: number) => {
  const a = Math.abs(n)
  if (a >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  return `$${n.toFixed(0)}`
}

function Metric({ label, m, format }:
  { label: string; m: QualityMetric | undefined; format: (n: number) => string }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <span className="text-sm text-stone-500">{label}</span>
      <span className="flex items-center gap-2">
        <ValueOrNA value={m?.value} format={format} reason={m?.reason} />
        {m?.source_kind && <SourceChip kind={m.source_kind} />}
      </span>
    </div>
  )
}

// 纯数值(非 metric 包装)的行，如 margins
function Plain({ label, value, format }:
  { label: string; value: number | undefined; format: (n: number) => string }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <span className="text-sm text-stone-500">{label}</span>
      <span className="flex items-center gap-2">
        <ValueOrNA value={value} format={format} />
        {typeof value === 'number' && <SourceChip kind="computed" />}
      </span>
    </div>
  )
}

const trendClass = (t: string) =>
  t === '加速' ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : t === '放缓' ? 'bg-red-50 text-red-700 border-red-200'
      : t === '基本持平' ? 'bg-stone-100 text-stone-600 border-stone-200'
        : 'bg-stone-100 text-stone-400 border-stone-200'  // 数据不足

function Trend({ label, t }: { label: string; t: QualityTrend | undefined }) {
  const ok = t && t.latest_growth != null && t.prior_growth != null
  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <span className="text-sm text-stone-500">{label}</span>
      <span className="flex items-center gap-2 text-sm">
        {ok ? (
          <>
            <span className="font-mono tabular-nums text-stone-700">
              {fmtPct(t!.prior_growth)} → {fmtPct(t!.latest_growth)}
            </span>
            <span className={`rounded border px-1.5 py-0.5 text-[11px] leading-none ${trendClass(t!.trend)}`}>
              {t!.trend}
            </span>
            <SourceChip kind={t!.source_kind} />
          </>
        ) : (
          <span title={t?.reason ? `不适用：${t.reason}` : '数据不足'}
            className="inline-flex items-center gap-1 rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-400 ring-1 ring-stone-200">
            <span className="text-stone-400">—</span>数据不足{t?.reason ? '（不适用）' : ''}
          </span>
        )}
      </span>
    </div>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-stone-400">{title}</div>
      <div className="divide-y divide-stone-100">{children}</div>
    </div>
  )
}

export default function CompanyQuality({ memo }: { memo: MemoData }) {
  const q = memo.quality
  if (!q) return null
  const m = q.metrics
  const mg = q.margins || {}
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold tracking-tight text-stone-700">公司质量</h2>
        <span className="text-xs text-stone-400">数字均由确定性工具算出 · 缺数据如实标"数据不足"</span>
      </div>

      <div className="grid gap-5 sm:grid-cols-3">
        <Block title="盈利能力">
          <Metric label="ROIC" m={m.roic} format={fmtPct} />
          <Metric label="ROE" m={m.roe} format={fmtPct} />
          <Plain label="毛利率" value={mg.gross_margin} format={fmtPct} />
          <Plain label="营业利润率" value={mg.operating_margin} format={fmtPct} />
          <Plain label="净利率" value={mg.net_margin} format={fmtPct} />
        </Block>

        <Block title="成长趋势">
          <Trend label="营收增速" t={m.revenue_trend} />
          <Trend label="净利增速" t={m.net_income_trend} />
        </Block>

        <Block title="财务健康">
          <Metric label="资产负债率" m={m.debt_to_assets} format={fmtPct} />
          <Metric label="净负债/EBITDA" m={m.net_debt_to_ebitda} format={mult} />
          <Metric label="现金及等价物" m={m.cash} format={bigMoney} />
          <Metric label="短债覆盖" m={m.short_term_debt_coverage} format={mult} />
        </Block>
      </div>

      {q.interpretation && (
        <p className="mt-4 border-t border-stone-100 pt-3 text-sm leading-relaxed text-stone-600">
          {q.interpretation}
        </p>
      )}
    </section>
  )
}
