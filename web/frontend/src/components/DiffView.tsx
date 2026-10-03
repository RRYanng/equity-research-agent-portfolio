import type { ReactNode } from 'react'
import type { WatchlistDiff } from '../types'
import { fmtMoney, fmtPct, ValueOrNA } from '../ui'

// 一行 diff：label + from → to；changed 时高亮(琥珀底 + ⚠️)，否则灰"未变"。
function Row({ label, changed, children }:
  { label: string; changed: boolean; children: ReactNode }) {
  return (
    <div className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm ${changed ? 'bg-amber-50' : ''}`}>
      <span className="w-24 shrink-0 text-xs text-stone-500">{label}</span>
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
      <span className={`ml-auto shrink-0 text-xs ${changed ? 'text-amber-600' : 'text-stone-300'}`}>
        {changed ? '⚠️ 变化' : '未变'}
      </span>
    </div>
  )
}

const Arrow = () => <span className="text-stone-300">→</span>

// 结构化"相比上次"：变化项醒目，没有可比历史时明确说明、绝不造对比。
export default function DiffView({ diff }: { diff: WatchlistDiff }) {
  if (!diff.available) {
    return (
      <div className="rounded bg-stone-50 px-3 py-2 text-xs text-stone-400 ring-1 ring-stone-200">
        📭 {diff.note ?? '暂无上次可对比'}
      </div>
    )
  }
  const c = diff.changes!
  const cur = diff.current!, prev = diff.previous!
  const evChanged = c.expected_value.from !== c.expected_value.to
  const perpChanged = c.implied_perp.from !== c.implied_perp.to
  const pct = c.expected_value.pct

  return (
    <div className="space-y-1">
      <div className="px-2 text-[11px] text-stone-400">
        上次 {prev.ts.replace('T', ' ')} &nbsp;→&nbsp; 本次 {cur.ts.replace('T', ' ')}
      </div>

      <Row label="评级" changed={c.rating_changed}>
        <span className="text-stone-500">{c.rating.from}</span>
        <Arrow />
        <span className="font-medium text-stone-900">{c.rating.to}</span>
      </Row>

      <Row label="估值锚" changed={evChanged}>
        <ValueOrNA value={c.expected_value.from} format={fmtMoney} />
        <Arrow />
        <ValueOrNA value={c.expected_value.to} format={fmtMoney} />
        {typeof pct === 'number' && (
          <span className={`text-xs ${pct >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
            ({pct > 0 ? '+' : ''}{pct}%)
          </span>
        )}
      </Row>

      <Row label="隐含永续增长" changed={perpChanged}>
        <ValueOrNA value={c.implied_perp.from} format={fmtPct} />
        <Arrow />
        <ValueOrNA value={c.implied_perp.to} format={fmtPct} />
      </Row>

      <Row label="镜头判定" changed={c.verdict_changed}>
        <span className="text-xs text-stone-500">
          DCF {prev.dcf_verdict ?? '—'} → {cur.dcf_verdict ?? '—'}
          &nbsp;·&nbsp; 倍数 {prev.mult_verdict ?? '—'} → {cur.mult_verdict ?? '—'}
        </span>
      </Row>
    </div>
  )
}
