"""
ResearchState 与各 *View schema —— 唯一真相源 (README.md)。

设计意图：这里每个 *View 就是将来 LangGraph 节点的输出契约。
原型里 stage 函数签名是 `state -> dict(对 state 的更新)`，刻意模仿
LangGraph 节点 `node(state) -> partial_state` 的形状，迁移时几乎零改动。

每个 View 都带一个 expectation_gap / marginal_change 字段，呼应五条原则的 1、2。
"""
from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated
from pydantic import BaseModel, Field


# ───────────────────────── 溯源 ─────────────────────────
class Citation(BaseModel):
    """每个量化结论的身份证：值 + 来源 + 时间戳 + 取数函数。原则 4。"""
    label: str                      # 这个数字是什么，如 "10Y Treasury yield"
    value: str                      # 字符串化的值，保留单位
    source: str                     # 数据来源，如 "yfinance ^TNX" / "tools.dcf"
    timestamp: str                  # 取数时间 (ISO)
    fn: str | None = None           # 算它的确定性函数（若有），如 "tools.dupont.dupont_roe"


class DataTier(str, Enum):
    PUBLIC = "public"       # 有 10-K/10-Q
    PRE_IPO = "pre_ipo"     # 数据稀疏，低置信度


# ───────────────────────── 环境层 ─────────────────────────
class MacroView(BaseModel):
    regime: str                              # 当前周期象限的一句话判断
    risk_free_rate: float                    # 无风险利率(小数, 如 0.043)
    equity_risk_premium: float               # ERP 假设(小数)
    base_discount_rate: float                # rf + ERP，市场基准(β=1)，供 valuation 做参照
    rate_path: str                           # 利率路径判断
    liquidity: str                           # 流动性环境
    expectation_gap: str                     # 市场共识 vs 现实的预期差
    marginal_change: str                     # 相比上期/共识，边际变好还是变坏 (原则 2)
    # FRED 三指标(Phase 3): {inflation, unemployment, yield_curve}，各含 value/as_of/source
    # 或 {value:None, reason}。数字全来自 FRED，LLM 只解读不写入。缺则数据不足，绝不编。
    indicators: dict = {}


class IndustryView(BaseModel):
    sector: str                              # 来自 yfinance 的硬分类
    industry: str                            # 来自 yfinance 的硬分类
    tam_ceiling: str                         # TAM 天花板(显式分析师估算，非硬数据)
    tam_is_estimate: bool = True             # 诚实标注：免费源拿不到 TAM
    tam_growth: str                          # TAM 增速判断
    structure: str                           # 竞争格局(集中度/五力)
    cycle_position: str                      # 景气位置
    valuation_percentile: str                # 行业估值分位判断
    expectation_gap: str
    marginal_change: str


# ───────────────────────── 标的层 ─────────────────────────
class CompanyView(BaseModel):
    business_model: str
    revenue_structure: str
    moat: str                                # 护城河类型与强度
    moat_trend: str                          # 护城河边际变化(变宽/变窄) (原则 2)
    growth_ceiling_check: str                # 显式引用 IndustryView.tam_ceiling 的约束结论
    expectation_gap: str
    marginal_change: str


class FinancialView(BaseModel):
    dupont: dict                             # 杜邦三因子(来自 tools，纯算)
    margins: dict                            # 毛利/营业/净利率 + 趋势
    fcf: dict                                # 自由现金流
    growth_quality: str                      # 真增长 vs 烧钱(OCF vs 净利润背离)
    quality: dict = Field(default_factory=dict)  # 公司质量卡片(ROIC/ROE/增速趋势/杠杆，纯算自 proto.quality)
    anomaly_flags: list[str] = Field(default_factory=list)
    marginal_change: str                     # 相比上期的边际财务变化 (原则 2)
    interpretation: str                      # LLM 对上述数字的解读
    citations: list[Citation] = Field(default_factory=list)


# ───────────────────────── 定价层 ─────────────────────────
class ValuationScenario(BaseModel):
    name: str                                # Bull / Base / Bear
    assumptions: dict                        # LLM 给的假设(增长/margin/terminal)
    per_share_value: float                   # tools.dcf 算出的每股价值
    rationale: str


class ValuationView(BaseModel):
    method: str                              # DCF / SOTP / comparables + 选用理由
    discount_rate_used: float                # β 调整后的 cost of equity (本次 DCF 真用的)
    beta: float
    discount_rate_basis: str                 # 折现率怎么来的(引用 macro)，溯源用
    fade_years: int = 0                      # 过渡期年数(两段式)
    buyback_shrink: float = 0.0              # 建模用的年化缩股率
    net_cash: float = 0.0                    # 修正口径净现金(正=净现金)
    scenarios: list[ValuationScenario] = Field(default_factory=list)
    current_price: float
    implied_perpetual_growth: float | None = None   # 反推：隐含永续增长(对比 GDP~3%)
    implied_explicit_cagr: float | None = None       # 反推：隐含显式期 CAGR(永续固定3%)
    implied_expectations: str = ""           # 反推结论的大白话
    expectation_gap: str = ""                # 隐含预期 vs 合理预期，合不合理 (原则 1)
    # —— 多镜头(#1/#2/#5) ——
    dcf_disabled: bool = False               # 方法路由是否关掉了 DCF
    low_confidence: bool = False             # DCF 低置信(未盈利但正FCF 等)
    method_reason: str = ""                  # 路由理由
    current_multiples: dict = Field(default_factory=dict)   # 当前 P/E、EV/EBITDA、EV/Sales
    fair_multiples: dict = Field(default_factory=dict)      # 同业/历史合理倍数带(显式估算)
    comparables_band: list = Field(default_factory=list)    # [lo, hi] 倍数隐含价值带
    comparables_midpoint: float | None = None
    rule_of_40: dict = Field(default_factory=dict)          # 成长股健康度(多镜头分支)
    dcf_verdict: str | None = None           # cheap/fair/expensive(DCF 镜头)
    mult_verdict: str | None = None          # cheap/fair/expensive(倍数镜头，三方组合后)
    multiples_detail: dict = Field(default_factory=dict)    # 三方交叉明细(Finnhub/Damodaran 各自 verdict + 溯源 + 分歧)
    nav: dict = Field(default_factory=dict)                 # NAV 资产净值块(仅资产持有型，纯算自 proto.nav，缺数据→数据不足)
    citations: list[Citation] = Field(default_factory=list)


class Catalyst(BaseModel):
    horizon: str                             # 3m / 6m / 12m
    event: str
    direction: str                           # 利好 / 利空 / 双向
    note: str = ""


# ───────────────────────── 检验层 ─────────────────────────
class RiskView(BaseModel):
    bear_thesis: str                         # 强制构建的空头逻辑
    bull_bear_debate: str                    # 一轮多空辩论
    risks_by_category: dict                  # 技术/竞争/监管/财务/估值/管理层/宏观
    falsifiers: list[str]                    # ≥3 条：哪些事件会证明逻辑错了


# ───────────────────────── 决策层 ─────────────────────────
class PositionRules(BaseModel):
    suggested_weight: str                    # 建议仓位
    entry: str                               # 建仓方式
    add: str                                 # 加仓条件
    trim: str                                # 减仓条件
    exit: str                                # 退出条件


class InvestmentMemo(BaseModel):
    ticker: str
    as_of: str
    one_liner: str                           # 一句话结论(以"隐含预期是否合理"框定)
    implied_expectation: str                 # 当前价格隐含预期
    scenario_probabilities: dict             # {Bull/Base/Bear: prob}
    expected_value_per_share: float | None   # 代码加权算出，非 LLM 心算；PRE_IPO 数据不足时 None
    rating: str                              # Buy/Hold/Sell (来自规则，多镜头一致性约束)
    confidence: str = "medium"               # high/medium/low (镜头分歧→low)
    rating_basis: str = ""                   # 评级依据(哪个规则触发)
    valuation_method: str = ""               # dcf / multiples
    target_price_range: str
    catalysts: list[Catalyst]
    risk_view: RiskView
    position_rules: PositionRules
    citations: list[Citation]


# ───────────────────────── 顶层 state ─────────────────────────
class ResearchState(BaseModel):
    ticker: str
    tier: DataTier | None = None
    raw_data: dict = Field(default_factory=dict)
    macro_view: MacroView | None = None
    industry_view: IndustryView | None = None
    company_view: CompanyView | None = None
    financial_view: FinancialView | None = None
    valuation_view: ValuationView | None = None
    catalysts: list[Catalyst] = Field(default_factory=list)
    risk_view: RiskView | None = None
    valuation_sensitivity: list = Field(default_factory=list)  # ERP 敏感性表
    # 市场共识信号(Phase 5 诚实版·非情绪分)：{analyst, short}。由 consensus_stage(committee 之后、
    # LLM-free)确定性算出，**仅作预期差对照展示，绝不驱动评级**——不进任何 LLM 节点 prompt。
    market_consensus: dict = Field(default_factory=dict)
    # 节点熔断留痕(Phase 9 ②)：哪些节点失败被降级。reducer 累加，committee/memo 据此注明。
    node_failures: Annotated[list, operator.add] = Field(default_factory=list)
    memo: InvestmentMemo | None = None
    # LangGraph reducer：节点返回 {"citations":[...]} 时累加而非覆盖(替代 run.py 的 _merge)。
    # operator.add 是 Annotated 元数据，Pydantic 忽略它，线性版照常用 .extend()。
    citations: Annotated[list[Citation], operator.add] = Field(default_factory=list)
