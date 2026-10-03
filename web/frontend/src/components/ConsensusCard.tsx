import type { MemoData } from '../types'
import { ValueOrNA, SourceChip, fmtPct } from '../ui'

// 市场共识 / 定位信号（Phase 5 诚实版·非情绪分）。
// 数字全来自后端 consensus_stage(LLM-free)：分析师 buy-side 占比月环比 + 短仓环比，硬数据、可溯源。
// 定位：仅作预期差的对照（共识 vs 三方镜头的背离本身是信息），**绝不驱动评级**——方向中性展示，
// 不上"好/坏"色（那是编辑判断）。复用现成 ValueOrNA+SourceChip+fmtPct，不新建判定、不碰四色映射。

const pp = (x: number) => `${x > 0 ? '+' : ''}${(x * 100).toFixed(1)}pp`
const pct = (x: number) => `${x > 0 ? '+' : ''}${(x * 100).toFixed(1)}%`

export default function ConsensusCard({ memo }: { memo: MemoData }) {
  const c = memo.consensus
  if (!c) return null
  const a = c.analyst, s = c.short
  const aShare = a.latest?.buy_side_share ?? null
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold tracking-tight text-stone-700">市场共识 / 定位信号</h2>
        <span className="text-xs text-stone-400">仅作预期差对照 · 不驱动本报告评级</span>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        {/* 分析师评级：buy-side 占比 + 月环比方向（中性） */}
        <div>
          <div className="mb-1 text-xs text-stone-500">分析师评级（buy-side 占比 · 月环比）</div>
          <div className="flex flex-wrap items-center gap-2">
            <ValueOrNA value={aShare} format={fmtPct} reason={a.reason} />
            {a.direction && (
              <span className="text-sm text-stone-700">
                {a.direction}
                {typeof a.buy_side_share_change === 'number' && `（${pp(a.buy_side_share_change)}）`}
              </span>
            )}
            {a.direction && <SourceChip kind="live" />}
          </div>
          {a.direction && a.latest && (
            <div className="mt-1 text-[10px] text-stone-400">
              {a.latest.buy_side}/{a.latest.total} buy-side · 截至 {a.as_of}
            </div>
          )}
        </div>

        {/* 短仓比例：占流通 + 月环比方向（中性） */}
        <div>
          <div className="mb-1 text-xs text-stone-500">短仓比例（占流通 · 月环比）</div>
          <div className="flex flex-wrap items-center gap-2">
            <ValueOrNA value={s.pct_of_float ?? null} format={fmtPct} reason={s.reason} />
            {s.direction && (
              <span className="text-sm text-stone-700">
                {s.direction}
                {typeof s.mom_change === 'number' && `（${pct(s.mom_change)}）`}
              </span>
            )}
            {s.direction && <SourceChip kind="live" />}
          </div>
          {s.direction && <div className="mt-1 text-[10px] text-stone-400">截至 {s.as_of}</div>}
        </div>
      </div>
    </section>
  )
}
