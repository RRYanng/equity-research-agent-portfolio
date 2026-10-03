"""
ResearchState → 前端结构化 JSON（Phase 10 step1）。

把"决策 + 三方镜头 + 分歧 + 每个数字的来源 + tier"全拆成独立字段，
让前端能做醒目高亮(置信/分歧/来源)。绝不退回 markdown。
"""
from __future__ import annotations


def source_kind(source: str | None) -> str:
    """把数据来源归类，前端据此上不同颜色 chip。"""
    s = (source or "").lower()
    if any(k in s for k in ("finnhub", "yfinance", "tnx", "fred")):
        return "live"          # 🟢 实时（含 FRED 官方宏观数据）
    if any(k in s for k in ("damodaran", "estimate", "assumption", "估算")):
        return "estimate"      # 🟡 估算
    if "llm" in s:
        return "llm"           # ⚪ LLM 未核实
    if any(k in s for k in ("tools", "code", "capm", "rf+erp", "quality", "computed")):
        return "computed"      # 🔵 确定性工具
    return "other"


def _citation(c) -> dict:
    return {"label": c.label, "value": c.value, "source": c.source,
            "source_kind": source_kind(c.source), "asof": c.timestamp, "fn": c.fn}


def _lenses(vv) -> dict | None:
    if vv is None:
        return None
    md = vv.multiples_detail or {}
    fh, dm, cc = md.get("finnhub"), md.get("damodaran"), md.get("cross_check", {})
    return {
        "dcf": {"verdict": vv.dcf_verdict, "disabled": vv.dcf_disabled, "method": vv.method},
        "finnhub": ({"verdict": fh.get("verdict"), "pe_band": fh.get("pe_band"),
                     "peers": fh.get("peers"), "n_peers": fh.get("n_peers"),
                     "asof": fh.get("asof"), "source_kind": "live"} if fh else None),
        "damodaran": ({"verdict": dm.get("verdict"), "ev_sales": dm.get("ev_sales"),
                       "industry": dm.get("industry"), "asof": dm.get("asof"),
                       "source_kind": "estimate"} if dm else None),
        "mult_verdict": vv.mult_verdict,
        "mult_source": md.get("source"),
        "disagreement": {
            "finnhub_vs_damodaran": cc.get("agree") is False,
            "dcf_vs_multiples": bool(vv.dcf_verdict and vv.mult_verdict
                                     and vv.dcf_verdict != vv.mult_verdict),
        },
    }


def _quality(fv) -> dict | None:
    """公司质量卡片：每个指标带 value(缺则 None) + reason + source_kind，前端据此画'数据不足'。"""
    if fv is None or not fv.quality:
        return None
    # margins 来自 tools.ratios(computed)，与质量指标同卡展示("保留已有毛利/营业/净利率")
    return {"metrics": fv.quality, "margins": fv.margins or {}, "interpretation": fv.interpretation}


def _nav(vv) -> dict | None:
    """NAV 资产净值块：仅资产持有型(crypto_treasury/suspected)出现；经营型 → None(普通股不出此区块)。"""
    n = vv.nav if vv else None
    if not n or n.get("type") == "operating":
        return None
    return n


def _macro(mv) -> dict | None:
    """宏观卡片：FRED 三指标(通胀/失业/收益率曲线)的 value+as_of+source+reason。
    数字全来自 macro_stage 存好的 mv.indicators(FRED 确定性取值)，这里只做展示拆分，不算不编。"""
    if mv is None or not mv.indicators:
        return None
    ind = mv.indicators
    infl = ind.get("inflation") or {}
    unemp = ind.get("unemployment") or {}
    curve = ind.get("yield_curve") or {}
    return {
        "inflation": {"value": infl.get("value"), "as_of": infl.get("as_of"),
                      "source": infl.get("source"), "reason": infl.get("reason")},
        "unemployment": {"value": unemp.get("value"), "as_of": unemp.get("as_of"),
                         "source": unemp.get("source"), "reason": unemp.get("reason")},
        "yield_curve": {"spread": curve.get("spread"), "inverted": curve.get("inverted"),
                        "dgs2": curve.get("dgs2"), "dgs10": curve.get("dgs10"),
                        "as_of": curve.get("as_of"), "source": curve.get("source"),
                        "reason": curve.get("reason")},
    }


def _consensus(state) -> dict | None:
    """市场共识信号卡片(Phase 5 诚实版·非情绪分)：分析师趋势 + 短仓，纯展示、仅作预期差对照。
    数字全来自 consensus_stage(LLM-free)存好的 state.market_consensus；缺 → reason，绝不编。"""
    mc = getattr(state, "market_consensus", None)
    if not mc:
        return None
    a = mc.get("analyst") or {}
    s = mc.get("short") or {}
    return {
        "analyst": {"direction": a.get("direction"), "latest": a.get("latest"),
                    "buy_side_share_change": a.get("buy_side_share_change"),
                    "as_of": a.get("as_of"), "source": a.get("source"), "reason": a.get("reason")},
        "short": {"direction": s.get("direction"), "pct_of_float": s.get("pct_of_float"),
                  "mom_change": s.get("mom_change"), "as_of": s.get("as_of"),
                  "source": s.get("source"), "reason": s.get("reason")},
    }


def serialize_state(state, *, cost=None, ceiling=None, diff=None,
                    stopped=False, notice="") -> dict:
    m, vv, rv = state.memo, state.valuation_view, state.risk_view
    fv = state.financial_view
    tier = state.tier.value if state.tier else None

    out = {
        "ticker": state.ticker,
        "as_of": (m.as_of if m else (state.raw_data or {}).get("as_of")),
        "tier": tier,
        "is_preipo": tier == "pre_ipo",
        "stopped": stopped, "notice": notice,
        "node_failures": list(state.node_failures or []),
        "cost": {"spent": cost, "ceiling": ceiling},
        "diff": diff,
        # 残缺/停机时给前端画"已完成阶段"
        "stages": {
            "data": state.tier is not None, "macro": state.macro_view is not None,
            "industry": state.industry_view is not None, "company": state.company_view is not None,
            "financial": state.financial_view is not None, "valuation": vv is not None,
            "risk": rv is not None, "committee": m is not None,
        },
    }

    out["decision"] = ({
        "rating": m.rating, "confidence": m.confidence,
        "low_confidence": m.confidence == "low",
        "one_liner": m.one_liner, "implied_expectation": m.implied_expectation,
        "rating_basis": m.rating_basis, "valuation_method": m.valuation_method,
        "expected_value_per_share": m.expected_value_per_share,
        "target_price_range": m.target_price_range,
    } if m else None)

    out["quality"] = _quality(fv)
    out["nav"] = _nav(vv)
    out["macro"] = _macro(state.macro_view)
    out["consensus"] = _consensus(state)
    out["lenses"] = _lenses(vv)

    out["valuation"] = ({
        "method": vv.method, "current_price": vv.current_price,
        "discount_rate_used": vv.discount_rate_used, "beta": vv.beta,
        "discount_rate_basis": vv.discount_rate_basis, "net_cash": vv.net_cash,
        "buyback_shrink": vv.buyback_shrink,
        "implied_perpetual_growth": vv.implied_perpetual_growth,
        "implied_explicit_cagr": vv.implied_explicit_cagr,
        "implied_expectations": vv.implied_expectations, "expectation_gap": vv.expectation_gap,
        "comparables_band": vv.comparables_band, "rule_of_40": vv.rule_of_40,
        "scenarios": [{"name": s.name, "per_share_value": s.per_share_value,
                       "assumptions": s.assumptions, "rationale": s.rationale,
                       "prob": (m.scenario_probabilities.get(s.name) if m else None)}
                      for s in vv.scenarios],
    } if vv else None)

    out["sensitivity"] = list(state.valuation_sensitivity or [])
    out["catalysts"] = ([{"horizon": c.horizon, "event": c.event,
                          "direction": c.direction, "note": c.note} for c in m.catalysts]
                        if m else [])
    out["risk"] = ({"bear_thesis": rv.bear_thesis, "bull_bear_debate": rv.bull_bear_debate,
                    "risks_by_category": rv.risks_by_category, "falsifiers": rv.falsifiers}
                   if rv else None)
    out["citations"] = [_citation(c) for c in (m.citations if m else [])]
    return out
