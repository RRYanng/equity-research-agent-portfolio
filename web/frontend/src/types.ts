// serializer 输出的结构化 memo 类型（与 web/api/serializers.py 对应）
export type SourceKind = 'live' | 'computed' | 'estimate' | 'llm' | 'other'

export interface Citation {
  label: string; value: string; source: string; source_kind: SourceKind; asof: string; fn: string | null
}
export interface PeBand { p25: number; median: number; p75: number; n: number }
export interface Lenses {
  dcf: { verdict: string | null; disabled: boolean; method: string }
  finnhub: { verdict: string | null; pe_band: PeBand | null; peers: string[] | null; n_peers: number | null; asof: string; source_kind: SourceKind } | null
  damodaran: { verdict: string | null; ev_sales: number | null; industry: string | null; asof: string; source_kind: SourceKind } | null
  mult_verdict: string | null
  mult_source: string | null
  disagreement: { finnhub_vs_damodaran: boolean; dcf_vs_multiples: boolean }
}
export interface Scenario {
  name: string; per_share_value: number | null; rationale: string
  prob: number | null; assumptions: { explicit_growth?: number[]; terminal_growth?: number }
}
export interface Valuation {
  method: string; current_price: number | null; discount_rate_used: number; beta: number
  net_cash: number; implied_perpetual_growth: number | null; implied_explicit_cagr: number | null
  implied_expectations: string; expectation_gap: string
  comparables_band: (number | null)[]; rule_of_40: Record<string, unknown>
  scenarios: Scenario[]
}
export interface Decision {
  rating: string; confidence: string; low_confidence: boolean
  one_liner: string; implied_expectation: string; rating_basis: string
  valuation_method: string; expected_value_per_share: number | null; target_price_range: string
}
export interface Risk {
  bear_thesis: string; bull_bear_debate: string
  risks_by_category: Record<string, string>; falsifiers: string[]
}
// 公司质量卡片（serializer 的 quality 块；缺数据 → value=null + reason，绝不编数字）
export interface QualityMetric { value: number | null; reason?: string; source_kind: SourceKind; tax_rate?: number }
export interface QualityTrend {
  latest_growth: number | null; prior_growth: number | null
  trend: string; reason?: string; source_kind: SourceKind
}
export interface Quality {
  metrics: {
    roic: QualityMetric; roe: QualityMetric
    revenue_trend: QualityTrend; net_income_trend: QualityTrend
    debt_to_assets: QualityMetric; net_debt_to_ebitda: QualityMetric
    cash: QualityMetric; short_term_debt_coverage: QualityMetric
  }
  margins: { gross_margin?: number; operating_margin?: number; net_margin?: number }
  interpretation: string
}
// NAV 资产净值块(仅资产持有型出现;经营型为 null)
export interface NavResult {
  value: number | null; reason?: string
  net_asset_value?: number; cash?: number; total_debt?: number; shares?: number
  current_price?: number | null; premium_discount?: number | null
}
export interface NavHolding { coin: string; count: number | null; source: string; as_of: string; cg_current_value_usd: number | null }
export interface Nav {
  type: 'crypto_treasury' | 'suspected_asset_holder'
  applicable: boolean; reason?: string; coin?: string | null
  holdings?: NavHolding[]
  coin_prices?: Record<string, { price: number; source: string; as_of: string } | null>
  crypto_value?: { value: number | null; reason?: string }
  result?: NavResult
  discount_notes?: string[]
}
// Watchlist（追踪列表 + 相比上次 diff；对应后端 proto/watchlist.py，残缺 run 已在后端 incomplete=0 隔离）
export interface WatchlistItem {
  ticker: string; rating: string | null; confidence: string | null
  expected_value: number | null; ts: string; method: string | null
}
export interface DiffSnapshot {
  rating: string; confidence: string; expected_value: number | null
  implied_perp: number | null; dcf_verdict: string | null; mult_verdict: string | null
  method: string | null; ts: string
}
export interface WatchlistDiff {
  ticker: string
  available: boolean          // 不足两次完整 run → false（前端显示"暂无上次可对比"，绝不造对比）
  note?: string
  current?: DiffSnapshot
  previous?: DiffSnapshot
  changes?: {
    rating_changed: boolean
    rating: { from: string; to: string }
    expected_value: { from: number | null; to: number | null; pct: number | null }  // pct 后端算好，前端不再造
    implied_perp: { from: number | null; to: number | null }                          // 无 pct，不硬算假 delta
    verdict_changed: boolean
  }
}
// 宏观卡片（FRED 三指标；数字全来自 macro_stage 存好的 mv.indicators，缺 → reason）
export interface MacroIndicator { value: number | null; as_of?: string; source?: string; reason?: string }
export interface YieldCurve {
  spread: number | null; inverted: boolean | null
  dgs2?: number | null; dgs10?: number | null; as_of?: string; source?: string; reason?: string
}
export interface Macro { inflation: MacroIndicator; unemployment: MacroIndicator; yield_curve: YieldCurve }
// 市场共识信号（Phase 5 诚实版·非情绪分）：仅作预期差对照，不驱动评级
export interface AnalystConsensus {
  direction: string | null
  latest?: { total?: number; buy_side?: number; buy_side_share?: number | null }
  buy_side_share_change?: number | null; as_of?: string; source?: string; reason?: string
}
export interface ShortInterest {
  direction: string | null; pct_of_float?: number | null; mom_change?: number | null
  as_of?: string; source?: string; reason?: string
}
export interface Consensus { analyst: AnalystConsensus; short: ShortInterest }
export interface MemoData {
  ticker: string; as_of: string; tier: string | null; is_preipo: boolean
  stopped: boolean; notice: string; node_failures: string[]
  cost: { spent: number | null; ceiling: number | null }
  decision: Decision | null; lenses: Lenses | null; valuation: Valuation | null
  quality: Quality | null; nav: Nav | null; macro: Macro | null; consensus: Consensus | null
  catalysts: { horizon: string; event: string; direction: string; note: string }[]
  risk: Risk | null; citations: Citation[]
}
