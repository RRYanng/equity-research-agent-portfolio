import { useState } from 'react'

interface Props {
  onAnalyze: (ticker: string) => void
  disabled: boolean
}

export default function TickerInput({ onAnalyze, disabled }: Props) {
  const [t, setT] = useState('')
  const go = () => { const v = t.trim().toUpperCase(); if (v) onAnalyze(v) }
  return (
    <div className="flex gap-2">
      <input
        value={t}
        onChange={(e) => setT(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && !disabled && go()}
        placeholder="股票代码 (AAPL / MSFT / SPACEX …)"
        disabled={disabled}
        className="flex-1 rounded-lg border border-stone-300 bg-white px-4 py-2.5 text-sm
                   outline-none focus:border-stone-800 disabled:opacity-50"
      />
      <button
        onClick={go}
        disabled={disabled || !t.trim()}
        className="rounded-lg bg-stone-900 px-5 py-2.5 text-sm text-white
                   hover:bg-stone-700 disabled:opacity-40"
      >
        {disabled ? '分析中…' : '分析'}
      </button>
    </div>
  )
}
