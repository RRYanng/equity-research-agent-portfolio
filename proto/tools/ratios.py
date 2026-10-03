"""
利润率 / FCF / 增长质量 —— 纯函数，零 LLM (README.md 原则 3)。
"""
from __future__ import annotations


def margins(gross_profit: float, operating_income: float, net_income: float, revenue: float) -> dict:
    """三条利润率。revenue 为 0 时报错而不是返回 NaN。"""
    if revenue == 0:
        raise ValueError("revenue 不能为 0")
    return {
        "gross_margin": gross_profit / revenue,
        "operating_margin": operating_income / revenue,
        "net_margin": net_income / revenue,
    }


def margin_trend(current: dict, prior: dict) -> dict:
    """边际变化：本期 vs 上期各利润率的 bp 变动 (原则 2)。"""
    out = {}
    for k in ("gross_margin", "operating_margin", "net_margin"):
        if k in current and k in prior:
            out[k + "_delta_bp"] = round((current[k] - prior[k]) * 10000, 1)
    return out


def free_cash_flow(operating_cash_flow: float, capex: float) -> dict:
    """FCF = 经营现金流 - 资本开支。capex 传正数(支出绝对值)。"""
    fcf = operating_cash_flow - abs(capex)
    return {"fcf": fcf, "operating_cash_flow": operating_cash_flow, "capex": abs(capex)}


def growth_quality(operating_cash_flow: float, net_income: float) -> dict:
    """
    增长质量：OCF vs 净利润背离检测。
    OCF/NI 持续 < 1 是"账面赚钱但收不到现金"的红旗(真增长 vs 烧钱/应计操纵)。
    """
    if net_income == 0:
        return {"ocf_to_ni": None, "flag": "净利润为 0，无法比较"}
    ratio = operating_cash_flow / net_income
    if ratio < 0.8:
        flag = "红旗：经营现金流显著低于净利润，盈利质量存疑"
    elif ratio > 1.2:
        flag = "健康：现金回收强于账面利润"
    else:
        flag = "正常：现金与利润大体匹配"
    return {"ocf_to_ni": ratio, "flag": flag}
