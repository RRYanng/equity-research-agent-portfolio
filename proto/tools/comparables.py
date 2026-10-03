"""
倍数交叉镜头(#2) —— 纯函数，零 LLM。

给一条独立于 DCF 的估值带 + 相对位置判断，作为对"单一 DCF 暴政"的 sanity check。
对未盈利标的另给 Rule-of-40 这类成长股专用尺子。
"""
from __future__ import annotations


def classify_valuation(current: float, fair_low: float, fair_high: float) -> str:
    """当前倍数落在合理带的哪一侧：cheap / fair / expensive。"""
    if current < fair_low:
        return "cheap"
    if current > fair_high:
        return "expensive"
    return "fair"


def comparables_valuation(eps, ebitda, sales, shares, net_debt, fair_multiples: dict) -> dict:
    """
    用一组"合理倍数"反算每股隐含价值带。net_debt 正=净负债，负=净现金。
    fair_multiples 可含 pe / ev_ebitda / ev_sales(缺哪个跳过哪个)。
    """
    implied = {}
    if eps is not None and fair_multiples.get("pe"):
        implied["pe"] = eps * fair_multiples["pe"]
    if ebitda is not None and fair_multiples.get("ev_ebitda") and shares:
        implied["ev_ebitda"] = (ebitda * fair_multiples["ev_ebitda"] - net_debt) / shares
    if sales is not None and fair_multiples.get("ev_sales") and shares:
        implied["ev_sales"] = (sales * fair_multiples["ev_sales"] - net_debt) / shares

    vals = [v for v in implied.values() if v is not None]
    band = (min(vals), max(vals)) if vals else (None, None)
    mid = sum(vals) / len(vals) if vals else None
    return {"implied_values": implied, "band": band, "midpoint": mid}


def rule_of_40(revenue_growth: float, fcf_margin: float) -> dict:
    """成长股健康度：营收增速 + FCF 利润率 >= 40% 为健康。输入用小数。"""
    score = (revenue_growth + fcf_margin) * 100
    return {"score": round(score, 1), "passes": score >= 40,
            "detail": f"营收增速 {revenue_growth*100:.0f}% + FCF利润率 {fcf_margin*100:.0f}% = {score:.0f}"}


def price_vs_band(price: float, band: tuple, tol: float = 0.0) -> str:
    """现价相对倍数隐含价值带的位置：cheap(低于带) / fair(带内) / expensive(高于带)。"""
    lo, hi = band
    if lo is None or hi is None:
        return "unknown"
    if price < lo * (1 - tol):
        return "cheap"
    if price > hi * (1 + tol):
        return "expensive"
    return "fair"
