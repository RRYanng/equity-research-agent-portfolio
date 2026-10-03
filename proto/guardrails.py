"""
节点 circuit breaker（Phase 9 ②）。

某节点抛【普通异常】→ 不拖垮全链：返回该节点的确定性降级视图(标 分析失败/low_confidence)，
留痕到 state.node_failures，下游用降级值继续，committee 在 memo 注明降级。

铁律：**放行 CostCeilingExceeded**（成本硬停信号）和 KeyboardInterrupt/SystemExit——
绝不能被熔断的 except 吞掉，否则刚做的成本闸就废了。三道机制正交：
  数据 fallback 返 None · 熔断吞普通异常降级 · 成本上限硬停。
"""
from __future__ import annotations

from .llm import CostCeilingExceeded
from .state import (
    DataTier, MacroView, IndustryView, CompanyView, FinancialView,
    ValuationView, RiskView, InvestmentMemo, PositionRules,
)

_ERP = 0.055   # 与 stages.EQUITY_RISK_PREMIUM 一致(降级默认值用)


def breaker(name: str, node_fn, fallback_fn):
    """包装一个图节点：普通异常 → 降级视图 + 留痕；放行硬停/中断信号。"""
    def wrapped(state):
        try:
            return node_fn(state)
        except (CostCeilingExceeded, KeyboardInterrupt, SystemExit):
            raise                              # 硬停/中断：必须放行，绝不吞
        except Exception as e:                 # noqa: BLE001 — 普通失败：降级续跑
            upd = dict(fallback_fn(state, e) or {})
            upd["node_failures"] = [f"{name}: {type(e).__name__}: {str(e)[:80]}"]
            return upd
    return wrapped


# ───────────────────────── 各节点的确定性降级视图 ─────────────────────────
def _fb_data(state, e):
    return {"raw_data": {"ticker": state.ticker, "tier": "public", "fundamentals": {},
                         "as_of": "n/a", "node_failed": "data"}, "tier": DataTier.PUBLIC}


def _fb_macro(state, e):
    rf = 0.043
    return {"macro_view": MacroView(
        regime="宏观节点失败，降级：用默认折现率(low_confidence)",
        risk_free_rate=rf, equity_risk_premium=_ERP, base_discount_rate=rf + _ERP,
        rate_path="数据不足", liquidity="数据不足",
        expectation_gap="数据不足", marginal_change="分析失败")}


def _fb_industry(state, e):
    rd = state.raw_data or {}
    return {"industry_view": IndustryView(
        sector=rd.get("sector") or "Unknown", industry=rd.get("industry") or "Unknown",
        tam_ceiling="行业节点失败，数据不足", tam_is_estimate=True, tam_growth="数据不足",
        structure="数据不足", cycle_position="数据不足", valuation_percentile="数据不足",
        expectation_gap="数据不足", marginal_change="分析失败")}


def _fb_company(state, e):
    return {"company_view": CompanyView(
        business_model="公司节点失败，降级", revenue_structure="数据不足",
        moat="数据不足", moat_trend="数据不足", growth_ceiling_check="数据不足",
        expectation_gap="数据不足", marginal_change="分析失败")}


def _fb_financial(state, e):
    return {"financial_view": FinancialView(
        dupont={}, margins={}, fcf={}, growth_quality="财务节点失败，降级（不估算）",
        anomaly_flags=[], marginal_change="分析失败", interpretation="财务节点失败，降级", citations=[])}


def _fb_valuation(state, e):
    rd = state.raw_data or {}
    return {"valuation_view": ValuationView(
        method="估值节点失败，无法估值（降级，不伪造）", discount_rate_used=0.0,
        beta=rd.get("beta") or 1.0, discount_rate_basis="n/a（节点失败）",
        current_price=rd.get("price") or 0.0, scenarios=[], dcf_disabled=True, low_confidence=True,
        method_reason="估值节点失败", implied_expectations="估值节点失败", expectation_gap="分析失败",
        mult_verdict=None, multiples_detail={"source": None, "low_confidence": True,
                                             "cross_check": {}, "note": "估值节点失败，降级"})}


def _fb_catalyst(state, e):
    return {"catalysts": []}


def _fb_risk(state, e):
    cats = ["技术", "竞争", "监管", "财务", "估值", "管理层", "宏观"]
    return {"risk_view": RiskView(
        bear_thesis="风险节点失败，降级，无法生成 bear case", bull_bear_debate="数据不足",
        risks_by_category={c: "数据不足（节点失败）" for c in cats},
        falsifiers=["风险节点失败，无法生成 falsifiers"])}


def _fb_committee(state, e):
    vv = state.valuation_view
    return {"memo": InvestmentMemo(
        ticker=state.ticker, as_of=(state.raw_data or {}).get("as_of", "n/a"),
        one_liner="委员会节点失败，降级：无法给出综合评级（不伪造）。",
        implied_expectation="数据不足", scenario_probabilities={}, expected_value_per_share=None,
        rating="降级（委员会失败）", confidence="low",
        rating_basis="committee 节点失败，熔断降级，不伪造评级", valuation_method="degraded",
        target_price_range="数据不足", catalysts=state.catalysts,
        risk_view=state.risk_view or RiskView(bear_thesis="—", bull_bear_debate="—",
                                              risks_by_category={}, falsifiers=["—"]),
        position_rules=PositionRules(suggested_weight="数据不足，不建仓", entry="—", add="—",
                                     trim="—", exit="—"),
        citations=state.citations)}


def _fb_sensitivity(state, e):
    return {"valuation_sensitivity": []}


def _fb_consensus(state, e):
    return {"market_consensus": {}}   # 降级 → 空，前端不出共识卡片（纯展示，不影响评级）


# 节点名 → 降级视图函数
FALLBACKS = {
    "data": _fb_data, "macro": _fb_macro, "industry": _fb_industry, "company": _fb_company,
    "financial": _fb_financial, "valuation": _fb_valuation, "catalyst": _fb_catalyst,
    "risk": _fb_risk, "committee": _fb_committee, "sensitivity": _fb_sensitivity,
    "consensus": _fb_consensus,
}
