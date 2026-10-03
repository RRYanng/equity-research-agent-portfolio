// SSE 客户端：连 /api/analyze/stream，解析 node/memo/stopped/done/error 事件。
import type { MemoData, WatchlistItem, WatchlistDiff } from '../types'

const API_BASE = (import.meta.env.VITE_API_BASE as string) || 'http://127.0.0.1:8011'

export type { MemoData }
export type NodeEvent = { node: string; status: 'done' | 'degraded'; cost: number }

export interface StreamHandlers {
  onNode: (e: NodeEvent) => void
  onMemo: (m: MemoData) => void
  onStopped: (m: MemoData) => void
  onDone: () => void
  onError: (msg: string) => void
}

// 历史记录：服务端归档的完整报告（刷新不丢 / 回看）。
export type ReportSummary = { id: number; ticker: string; as_of: string; rating: string | null; saved_at: string }

export async function listReports(): Promise<ReportSummary[]> {
  const r = await fetch(`${API_BASE}/api/reports`)
  if (!r.ok) throw new Error('加载历史失败')
  return (await r.json()).items
}

export async function getReport(id: number): Promise<MemoData> {
  const r = await fetch(`${API_BASE}/api/reports/${id}`)
  if (!r.ok) throw new Error('加载报告失败')
  return await r.json()
}

// 关注列表：追踪标的的最近一次完整结论摘要（后端已排除残缺 run）。
export async function listWatchlist(): Promise<WatchlistItem[]> {
  const r = await fetch(`${API_BASE}/api/watchlist`)
  if (!r.ok) throw new Error('加载关注列表失败')
  return (await r.json()).items
}

// 相比上次：最近两次完整 run 的结构化 diff（不足两次 → available:false）。
export async function getWatchlistDiff(ticker: string): Promise<WatchlistDiff> {
  const r = await fetch(`${API_BASE}/api/watchlist/${encodeURIComponent(ticker)}/diff`)
  if (!r.ok) throw new Error('加载 diff 失败')
  return await r.json()
}

export function analyzeStream(ticker: string, handlers: StreamHandlers, ceiling?: number): () => void {
  const params = new URLSearchParams({ ticker })
  if (ceiling != null) params.set('ceiling', String(ceiling))
  const es = new EventSource(`${API_BASE}/api/analyze/stream?${params.toString()}`)
  let finished = false
  const close = () => { finished = true; es.close() }

  es.addEventListener('node', (ev) => handlers.onNode(JSON.parse((ev as MessageEvent).data)))
  es.addEventListener('memo', (ev) => { handlers.onMemo(JSON.parse((ev as MessageEvent).data)); close() })
  es.addEventListener('stopped', (ev) => { handlers.onStopped(JSON.parse((ev as MessageEvent).data)); close() })
  es.addEventListener('done', () => { handlers.onDone(); close() })
  es.addEventListener('error', (ev) => {
    const data = (ev as MessageEvent).data
    if (data) { handlers.onError(JSON.parse(data).message ?? 'stream error'); close() }
    else if (!finished) { handlers.onError('连接中断（后端是否在 8011 运行？）'); close() }
  })
  return close
}
