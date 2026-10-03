import { useState } from 'react'
import TickerInput from './components/TickerInput'
import ProgressStepper, { STEPS } from './components/ProgressStepper'
import Result from './components/Result'
import HistoryList from './components/HistoryList'
import Watchlist from './components/Watchlist'
import { analyzeStream, getReport, type NodeEvent } from './api/client'
import type { MemoData } from './types'

type Status = 'idle' | 'running' | 'done' | 'stopped' | 'error'

export default function App() {
  const [status, setStatus] = useState<Status>('idle')
  const [completed, setCompleted] = useState<Record<string, 'done' | 'degraded'>>({})
  const [cost, setCost] = useState(0)
  const [memo, setMemo] = useState<MemoData | null>(null)
  const [errMsg, setErrMsg] = useState('')
  const [fromHistory, setFromHistory] = useState(false)   // 当前结果是回看历史(隐藏进度条)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [historyKey, setHistoryKey] = useState(0)         // bump → 重拉历史列表 + 关注列表
  const [browseTab, setBrowseTab] = useState<'history' | 'watchlist'>('history')

  const current = status === 'running'
    ? (STEPS.find((s) => !completed[s.key])?.key ?? null)
    : null

  const analyze = (tk: string) => {
    setStatus('running'); setCompleted({}); setCost(0); setMemo(null); setErrMsg('')
    setFromHistory(false); setActiveId(null)
    analyzeStream(tk, {
      onNode: (e: NodeEvent) => { setCompleted((c) => ({ ...c, [e.node]: e.status })); setCost(e.cost) },
      onMemo: (m) => { setMemo(m); setCost(m.cost?.spent ?? 0); setStatus('done'); setHistoryKey((k) => k + 1) },
      onStopped: (m) => { setMemo(m); setCost(m.cost?.spent ?? 0); setStatus('stopped') },
      onDone: () => setStatus((s) => (s === 'running' ? 'done' : s)),
      onError: (msg) => { setErrMsg(msg); setStatus('error') },
    })
  }

  // 回看历史：拉完整报告 json → 复用 <Result/> 渲染。不跑分析、不花钱。
  const viewReport = (id: number) => {
    setErrMsg(''); setActiveId(id); setFromHistory(true)
    getReport(id)
      .then((m) => { setMemo(m); setCost(m.cost?.spent ?? 0); setStatus('done') })
      .catch((e) => { setErrMsg(String(e.message ?? e)); setStatus('error') })
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto max-w-3xl px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">📊 Equity Research</h1>
          <p className="text-xs text-stone-400">研究分析工具 · 不构成投资建议</p>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <TickerInput onAnalyze={analyze} disabled={status === 'running'} />

        <section className="space-y-2">
          <div className="inline-flex rounded-lg border border-stone-200 bg-white p-0.5 text-xs">
            {(['history', 'watchlist'] as const).map((t) => (
              <button key={t} onClick={() => setBrowseTab(t)}
                className={`rounded-md px-3 py-1 transition-colors ${
                  browseTab === t ? 'bg-stone-800 text-white' : 'text-stone-500 hover:text-stone-700'}`}>
                {t === 'history' ? '历史记录' : '关注列表'}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-stone-400">
            {browseTab === 'history'
              ? '每次分析的完整存档 · 点开回看整份报告（不重算）'
              : '追踪标的的最近结论 + 相比上次 · 点开看结构化变化（不跑分析）'}
          </p>
          {browseTab === 'history'
            ? <HistoryList refreshKey={historyKey} activeId={activeId} onSelect={viewReport} />
            : <Watchlist refreshKey={historyKey} />}
        </section>

        {status !== 'idle' && !fromHistory && <ProgressStepper completed={completed} current={current} cost={cost} />}

        {status === 'error' && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">分析出错：{errMsg}</div>
        )}

        {status === 'stopped' && memo && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
            <div className="font-semibold">⚠️ 已停（触及成本上限）</div>
            <div className="mt-1">{memo.notice}</div>
            <div className="mt-1 text-xs">实际花费 ${memo.cost?.spent} / 上限 ${memo.cost?.ceiling}</div>
          </div>
        )}

        {status === 'done' && memo && (
          <div className="space-y-2">
            {fromHistory && (
              <div className="text-xs text-stone-400">📂 回看历史报告（{memo.ticker} · as of {memo.as_of}）— 已归档，未重新计算。</div>
            )}
            <Result memo={memo} />
          </div>
        )}
      </main>
    </div>
  )
}
