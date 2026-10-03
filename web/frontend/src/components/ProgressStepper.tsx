// 实时进度：9-10 个节点一层层点亮。当前在跑的显示"进行中"。
export const STEPS: { key: string; label: string }[] = [
  { key: 'data', label: '数据/分级' },
  { key: 'macro', label: '宏观' },
  { key: 'industry', label: '行业' },
  { key: 'company', label: '公司' },
  { key: 'financial', label: '财务' },
  { key: 'valuation', label: '估值' },
  { key: 'catalyst', label: '催化剂' },
  { key: 'risk', label: '风险' },
  { key: 'committee', label: '委员会' },
  { key: 'sensitivity', label: '敏感性 / Memo' },
]

interface Props {
  completed: Record<string, 'done' | 'degraded'>
  current: string | null
  cost: number
}

export default function ProgressStepper({ completed, current, cost }: Props) {
  return (
    <div className="border border-stone-200 rounded-xl bg-white p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm text-stone-500">分析进行中</span>
        <span className="text-xs text-stone-400 tabular-nums">已花 ${cost.toFixed(3)}</span>
      </div>
      <ol className="flex flex-wrap gap-x-2 gap-y-3">
        {STEPS.map((s) => {
          const st = completed[s.key]
          const isCurrent = current === s.key
          let dot = 'bg-stone-200 text-stone-400'      // 未开始
          let mark = '○'
          if (st === 'done') { dot = 'bg-emerald-500 text-white'; mark = '✓' }
          else if (st === 'degraded') { dot = 'bg-amber-500 text-white'; mark = '!' }
          else if (isCurrent) { dot = 'bg-sky-500 text-white animate-pulse'; mark = '…' }
          return (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${dot}`}>{mark}</span>
              <span className={`text-sm ${st || isCurrent ? 'text-stone-800' : 'text-stone-400'}`}>{s.label}</span>
              {isCurrent && <span className="text-xs text-sky-600">进行中</span>}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
