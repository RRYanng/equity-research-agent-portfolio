"""
公司质量指标 —— 纯函数，零 LLM、零网络 (README.md 原则 3)。

刻意不放进 tools/（tools/ 是冻结资产）；这是新的独立纯函数模块。
LLM 只解读这些算好的数字，绝不负责"算"或"猜"任何一个。

零伪造头号原则（守死）：
  · 任一关键输入缺失 → 返回 {"value": None, "reason": "..."}，**绝不返回一个编造的数字**。
  · 负基数（上期 ≤ 0）的同比增速无意义 → 标"不适用"，不硬算出误导性百分比。

每个指标自带 source_kind 溯源标签，与现有 citation 体系一致：
  · "computed" —— 由本模块确定性算出（ROIC/负债比/增速…）。
  · "live"     —— 直接取自实时财报字段（如现金余额）。
"""
from __future__ import annotations

_CK = "computed"   # source_kind: 确定性工具算出


def _na(reason: str) -> dict:
    """数据不足：值为 None（绝不是数字）+ 原因，统一形状。"""
    return {"value": None, "reason": reason, "source_kind": _CK}


def _missing(**fields) -> str | None:
    """返回第一个为 None 的字段名（用于生成精确的'缺什么'原因）；都在则 None。"""
    for name, v in fields.items():
        if v is None:
            return name
    return None


# ───────────────────────── 盈利能力 ─────────────────────────
def roic(operating_income, tax_provision, pretax_income,
         total_debt, shareholders_equity) -> dict:
    """
    ROIC = NOPAT / 投入资本。
      NOPAT = 营业利润 ×(1 − 有效税率)；有效税率 = 税 / 税前利润，clamp 到 [0,1]。
      亏损期(税前 ≤ 0)：税率视为 0（无税盾），NOPAT=营业利润，ROIC 如实为负、不掩盖。
      投入资本 = 总债务 + 股东权益。
    任一关键字段缺失 → 数据不足。
    """
    miss = _missing(operating_income=operating_income, tax_provision=tax_provision,
                    pretax_income=pretax_income, total_debt=total_debt,
                    shareholders_equity=shareholders_equity)
    if miss:
        return _na(f"缺字段 {miss}，ROIC 无法计算")
    invested_capital = total_debt + shareholders_equity
    if invested_capital == 0:
        return _na("投入资本(总债务+权益)为 0，ROIC 无法计算")
    tax_rate = min(1.0, max(0.0, tax_provision / pretax_income)) if pretax_income > 0 else 0.0
    nopat = operating_income * (1 - tax_rate)
    return {"value": nopat / invested_capital, "nopat": nopat,
            "invested_capital": invested_capital, "tax_rate": tax_rate,
            "source_kind": _CK, "fn": "proto.quality.roic"}


def roe(net_income, shareholders_equity) -> dict:
    """ROE = 净利润 / 股东权益。权益为 0 或缺失 → 数据不足。"""
    miss = _missing(net_income=net_income, shareholders_equity=shareholders_equity)
    if miss:
        return _na(f"缺字段 {miss}，ROE 无法计算")
    if shareholders_equity == 0:
        return _na("股东权益为 0，ROE 无法计算")
    return {"value": net_income / shareholders_equity,
            "source_kind": _CK, "fn": "proto.quality.roe"}


# ───────────────────────── 成长趋势 ─────────────────────────
def yoy_growth(current, prior) -> dict:
    """
    同比增速 = 本期/上期 − 1。
    上期 ≤ 0（负基数或 0）→ 同比增速无意义，标"不适用"，绝不硬算出百分比。
    """
    miss = _missing(current=current, prior=prior)
    if miss:
        return _na(f"缺字段 {miss}，同比增速无法计算")
    if prior <= 0:
        return _na("上期基数 ≤ 0，同比增速不适用（负/零基数算出的百分比会误导）")
    return {"value": current / prior - 1,
            "source_kind": _CK, "fn": "proto.quality.yoy_growth"}


def growth_trend(current, prior, prior2) -> dict:
    """
    趋势：本期增速 vs 上期增速 → 加速 / 放缓 / 基本持平。
    任一增速算不出(缺字段或负基数) → trend="数据不足"，对应增速为 None，不编造。
    """
    latest = yoy_growth(current, prior)
    earlier = yoy_growth(prior, prior2)
    lg, eg = latest["value"], earlier["value"]
    out = {"latest_growth": lg, "prior_growth": eg,
           "source_kind": _CK, "fn": "proto.quality.growth_trend"}
    if lg is None or eg is None:
        out["trend"] = "数据不足"
        out["reason"] = latest.get("reason") or earlier.get("reason")
        return out
    diff = lg - eg
    out["trend"] = "加速" if diff > 0.001 else "放缓" if diff < -0.001 else "基本持平"
    return out


# ───────────────────────── 财务健康 ─────────────────────────
def debt_to_assets(total_assets, shareholders_equity) -> dict:
    """
    资产负债率 = 总负债 / 总资产，总负债 = 总资产 − 股东权益（会计恒等式）。
    缺字段或总资产为 0 → 数据不足。
    """
    miss = _missing(total_assets=total_assets, shareholders_equity=shareholders_equity)
    if miss:
        return _na(f"缺字段 {miss}，资产负债率无法计算")
    if total_assets == 0:
        return _na("总资产为 0，资产负债率无法计算")
    liabilities = total_assets - shareholders_equity
    return {"value": liabilities / total_assets, "total_liabilities": liabilities,
            "source_kind": _CK, "fn": "proto.quality.debt_to_assets"}


def net_debt_to_ebitda(net_debt, ebitda) -> dict:
    """
    净负债 / EBITDA（杠杆与偿债压力）。
    EBITDA 缺失或 ≤ 0 → 不适用（非正 EBITDA 下该比率无意义）。
    """
    miss = _missing(net_debt=net_debt, ebitda=ebitda)
    if miss:
        return _na(f"缺字段 {miss}，净负债/EBITDA 无法计算")
    if ebitda <= 0:
        return _na("EBITDA ≤ 0，净负债/EBITDA 不适用")
    return {"value": net_debt / ebitda,
            "source_kind": _CK, "fn": "proto.quality.net_debt_to_ebitda"}


def short_term_debt_coverage(cash, current_debt) -> dict:
    """
    短期债务覆盖 = 现金及等价物 / 短期(一年内到期)债务。≥1 表示现金可覆盖短债。
    缺字段 → 数据不足；短债为 0 → 无短期偿债压力（标注，不返回除零数字）。
    """
    miss = _missing(cash=cash, current_debt=current_debt)
    if miss:
        return _na(f"缺字段 {miss}，短债覆盖无法计算")
    if current_debt == 0:
        return _na("无短期债务（短债为 0），无偿债压力")
    return {"value": cash / current_debt,
            "source_kind": _CK, "fn": "proto.quality.short_term_debt_coverage"}


# ───────────────────────── 汇总器 ─────────────────────────
def company_quality(f: dict, net_debt=None) -> dict:
    """
    从 fundamentals 字段一次性算出整张"公司质量"卡片所需指标。
    每一项独立降级——某项缺字段只让该项标"数据不足"，绝不连坐、绝不编造。
    f 用 .get()，缺键即 None，自然走各函数的"数据不足"分支。
    """
    g = f.get
    cash_metric = {"value": g("cash"), "source_kind": "live",
                   "fn": "yfinance balance_sheet"} if g("cash") is not None \
        else _na("缺现金及等价物字段")
    return {
        # 盈利能力
        "roic": roic(g("operating_income"), g("tax_provision"), g("pretax_income"),
                     g("total_debt"), g("shareholders_equity")),
        "roe": roe(g("net_income"), g("shareholders_equity")),
        # 成长趋势
        "revenue_trend": growth_trend(g("revenue"), g("revenue_prior"), g("revenue_prior2")),
        "net_income_trend": growth_trend(g("net_income"), g("net_income_prior"),
                                         g("net_income_prior2")),
        # 财务健康
        "debt_to_assets": debt_to_assets(g("total_assets"), g("shareholders_equity")),
        "net_debt_to_ebitda": net_debt_to_ebitda(net_debt, g("ebitda")),
        "cash": cash_metric,
        "short_term_debt_coverage": short_term_debt_coverage(g("cash"), g("current_debt")),
    }
