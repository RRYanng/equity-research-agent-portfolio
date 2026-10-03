import type { MemoData } from '../types'
import { SourceChip, verdictClass, verdictLabel } from '../ui'
import type { SourceKind } from '../types'
import type { ReactNode } from 'react'

function Lens({ title, verdict, sub, kind, disagree }:
  { title: string; verdict: string | null; sub: ReactNode; kind: SourceKind; disagree: boolean }) {
  return (
    <div className={`flex-1 rounded-lg border p-3 ${disagree
      ? 'border-amber-300 border-l-4 border-l-amber-400 bg-amber-50/70' : 'border-stone-200 bg-white'}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-stone-500">{title}</span>
        <SourceChip kind={kind} />
      </div>
      <div className={`mt-1 text-lg font-semibold ${verdictClass(verdict)}`}>{verdictLabel(verdict)}</div>
      <div className="text-[11px] leading-tight text-stone-400">{sub}</div>
    </div>
  )
}

export default function ThreeLensCard({ memo }: { memo: MemoData }) {
  const L = memo.lenses
  if (!L) return null
  const { finnhub_vs_damodaran: fhDis, dcf_vs_multiples: dcfDis } = L.disagreement
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold text-stone-700">三方镜头交叉</h2>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Lens title="DCF" kind="computed" disagree={dcfDis}
          verdict={L.dcf.disabled ? null : L.dcf.verdict}
          sub={L.dcf.disabled ? '已关闭(负FCF·路由倍数法)' : '两段式 per-share'} />
        {L.finnhub && <Lens title="Finnhub 同业 P/E（主）" kind="live" disagree={fhDis || dcfDis}
          verdict={L.finnhub.verdict}
          sub={`${L.finnhub.n_peers} 家 · P/E 中位 ${L.finnhub.pe_band?.median ?? '—'} · live`} />}
        {L.damodaran && <Lens title="Damodaran 行业 EV/Sales（参照）" kind="estimate" disagree={fhDis}
          verdict={L.damodaran.verdict}
          sub={`${L.damodaran.industry} · EV/S ${L.damodaran.ev_sales} · asof ${L.damodaran.asof}`} />}
      </div>
      {(fhDis || dcfDis) && (
        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <div className="font-medium">⚠️ 镜头分歧 —— 这正是置信度低的原因：</div>
          <ul className="mt-1 list-disc pl-5 space-y-0.5">
            {dcfDis && <li>DCF 看「{verdictLabel(L.dcf.verdict)}」，但倍数镜头看「{verdictLabel(L.mult_verdict)}」</li>}
            {fhDis && <li>Finnhub 同业看「{verdictLabel(L.finnhub?.verdict ?? null)}」，但 Damodaran 行业看「{verdictLabel(L.damodaran?.verdict ?? null)}」</li>}
          </ul>
        </div>
      )}
    </section>
  )
}
