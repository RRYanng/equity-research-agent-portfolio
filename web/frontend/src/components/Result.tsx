import type { MemoData } from '../types'
import { SourceChip } from '../ui'
import DecisionBar from './DecisionBar'
import MacroCard from './MacroCard'
import ConsensusCard from './ConsensusCard'
import CompanyQuality from './CompanyQuality'
import NavSection from './NavSection'
import ThreeLensCard from './ThreeLensCard'
import ValuationSection from './ValuationSection'
import CatalystTimeline from './CatalystTimeline'
import RiskSection from './RiskSection'

export default function Result({ memo }: { memo: MemoData }) {
  return (
    <div className="space-y-6">
      <DecisionBar memo={memo} />

      <MacroCard memo={memo} />

      {memo.node_failures.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          ⚠️ 有节点降级（熔断续跑，置信已降）：{memo.node_failures.join('；')}
        </div>
      )}

      <CompanyQuality memo={memo} />

      {memo.is_preipo ? (
        <div className="rounded-xl border border-stone-300 bg-stone-100 p-5">
          <div className="text-base font-medium text-stone-700">数据不足 · 无法估值（PRE_IPO / 数据稀疏）</div>
          {memo.decision && <p className="mt-1 text-sm leading-relaxed text-stone-600">{memo.decision.one_liner}</p>}
          <ul className="mt-2 list-disc pl-5 text-sm text-stone-500">
            <li>DCF：未运行（缺 FCF/营收等关键字段，禁用 LLM 估算 → 不伪造）</li>
            <li>倍数：无真源 → 无判定</li>
            <li>缺失财务字段一律标 None，不估算、不补值</li>
          </ul>
        </div>
      ) : (
        <>
          <ThreeLensCard memo={memo} />
          <ValuationSection memo={memo} />
        </>
      )}

      <NavSection memo={memo} />

      <ConsensusCard memo={memo} />

      <CatalystTimeline memo={memo} />
      <RiskSection memo={memo} />

      {memo.citations.length > 0 && (
        <details className="rounded-xl border border-stone-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold text-stone-700">
            溯源 Citations（{memo.citations.length}）
          </summary>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[26rem] text-xs">
              <tbody>
                {memo.citations.map((c, i) => (
                  <tr key={i} className="border-t border-stone-100">
                    <td className="py-1 pr-2 text-stone-500">{c.label}</td>
                    <td className="py-1 pr-2 font-mono tabular-nums">{c.value}</td>
                    <td className="py-1 pr-2"><SourceChip kind={c.source_kind} /></td>
                    <td className="py-1 text-stone-400">{c.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}
