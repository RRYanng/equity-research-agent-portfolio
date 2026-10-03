"""
简化 DCF —— 纯函数，零 LLM 依赖 (README.md 原则 3、§6)。

LLM 只负责给假设(增长率/折现率来自 macro/financial)，真正的折现算账在这里。
中间过程全部可导出，方便 Memo 溯源 (原则 4)。
"""
from __future__ import annotations


def project_fcf(base_fcf: float, growth_rates: list[float]) -> list[float]:
    """按逐年增长率把基准 FCF 滚出来。growth_rates 是每年的增长率(小数)。"""
    fcfs = []
    prev = base_fcf
    for g in growth_rates:
        prev = prev * (1.0 + g)
        fcfs.append(prev)
    return fcfs


def dcf_value(
    base_fcf: float,
    growth_rates: list[float],
    discount_rate: float,
    terminal_growth: float,
    net_debt: float,
    shares_outstanding: float,
) -> dict:
    """
    两段式 DCF：显式期逐年折现 + 戈登永续终值。

    返回 enterprise value / equity value / 每股价值 + 完整中间过程(溯源用)。
    约束：discount_rate 必须 > terminal_growth，否则永续公式发散。
    """
    if discount_rate <= terminal_growth:
        raise ValueError(
            f"discount_rate({discount_rate}) 必须 > terminal_growth({terminal_growth})，否则终值发散"
        )
    if shares_outstanding <= 0:
        raise ValueError("shares_outstanding 必须 > 0")

    fcfs = project_fcf(base_fcf, growth_rates)

    pv_explicit = 0.0
    pv_by_year = []
    for i, fcf in enumerate(fcfs, start=1):
        pv = fcf / ((1.0 + discount_rate) ** i)
        pv_by_year.append(pv)
        pv_explicit += pv

    n = len(fcfs)
    terminal_fcf = fcfs[-1] * (1.0 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1.0 + discount_rate) ** n)

    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - net_debt
    per_share = equity_value / shares_outstanding

    return {
        "per_share_value": per_share,
        "equity_value": equity_value,
        "enterprise_value": enterprise_value,
        "pv_explicit": pv_explicit,
        "pv_terminal": pv_terminal,
        "terminal_value": terminal_value,
        "projected_fcf": fcfs,
        "pv_by_year": pv_by_year,
        "inputs": {
            "base_fcf": base_fcf,
            "growth_rates": growth_rates,
            "discount_rate": discount_rate,
            "terminal_growth": terminal_growth,
            "net_debt": net_debt,
            "shares_outstanding": shares_outstanding,
        },
    }


def sensitivity_table(
    base_fcf: float,
    growth_rates: list[float],
    net_debt: float,
    shares_outstanding: float,
    discount_rates: list[float],
    terminal_growths: list[float],
) -> dict:
    """对(折现率 × 永续增长)网格做每股价值敏感性。返回可直接渲染的二维表。"""
    rows = []
    for r in discount_rates:
        row = []
        for tg in terminal_growths:
            if r <= tg:
                row.append(None)  # 不合法组合，留空
            else:
                v = dcf_value(base_fcf, growth_rates, r, tg, net_debt, shares_outstanding)
                row.append(round(v["per_share_value"], 2))
        rows.append(row)
    return {
        "discount_rates": discount_rates,
        "terminal_growths": terminal_growths,
        "values": rows,
    }


def _growth_path(explicit_growth: list[float], fade_years: int, terminal_growth: float) -> list[float]:
    """
    两段式增长路径(change 1)：显式期逐年增长 + 过渡期线性 fade 到永续增长。
    例：显式 [8%,8%,7%,6%,6%] + fade 5年 -> 从 6% 线性收敛到 terminal(如3%)。
    不再把全部溢价压在前5年。
    """
    path = list(explicit_growth)
    if fade_years > 0:
        last = explicit_growth[-1] if explicit_growth else terminal_growth
        for k in range(1, fade_years + 1):
            # 第k步：在 last 和 terminal 之间线性插值
            g = last + (terminal_growth - last) * k / fade_years
            path.append(g)
    return path


def dcf_two_stage_per_share(
    base_fcf: float,
    shares: float,
    net_cash: float,
    explicit_growth: list[float],
    fade_years: int,
    terminal_growth: float,
    discount_rate: float,
    buyback_shrink: float = 0.0,
) -> dict:
    """
    两段式 + 每股 owner-earnings DCF。

    建模视角(change 3)：站在长期持有、永不卖出的股东角度——公司持续回购缩股，
    每股能分到的 FCF 逐年增长更快(总量增速 + 缩股带来的每股增厚)。
    故对"每股 FCF"按 (1+总量增速)/(1-缩股率) 滚动；缩股只在显式+过渡期生效，
    永续期保守地关掉回购增厚(回购不可能永远当增长源)。

    net_cash(change 4)：正=净现金，按面值加到每股价值上(它是当下就存在的资产)。
    返回每股价值 + 全部中间过程(溯源用)。
    """
    if discount_rate <= terminal_growth:
        raise ValueError(f"discount_rate({discount_rate}) 必须 > terminal_growth({terminal_growth})")
    if shares <= 0:
        raise ValueError("shares 必须 > 0")
    if base_fcf <= 0:
        # 硬闸(#1)：DCF 对非正现金流无定义——复利负现金流会让"增长越高估值越低"，
        # 求解器单调性也失效。负/微 FCF 必须由 method_router 路由到倍数法。
        raise ValueError(
            f"base_fcf({base_fcf}) <= 0：DCF 不适用于非正现金流标的，请走 method_router 改用倍数法"
        )

    fcf_ps0 = base_fcf / shares
    path = _growth_path(explicit_growth, fade_years, terminal_growth)
    accretion = 1.0 / (1.0 - buyback_shrink) if buyback_shrink < 1 else 1.0

    fcf_ps = fcf_ps0
    pv_stage = 0.0
    pv_by_year = []
    for t, g in enumerate(path, start=1):
        fcf_ps = fcf_ps * (1.0 + g) * accretion     # 每股增厚 = 总量增长 × 缩股增厚
        pv = fcf_ps / ((1.0 + discount_rate) ** t)
        pv_by_year.append(pv)
        pv_stage += pv

    n = len(path)
    terminal_fcf_ps = fcf_ps * (1.0 + terminal_growth)        # 永续期不再加回购增厚
    terminal_value_ps = terminal_fcf_ps / (discount_rate - terminal_growth)
    pv_terminal = terminal_value_ps / ((1.0 + discount_rate) ** n)

    operating_value_ps = pv_stage + pv_terminal
    net_cash_ps = net_cash / shares
    value_ps = operating_value_ps + net_cash_ps

    return {
        "per_share_value": value_ps,
        "operating_value_ps": operating_value_ps,
        "net_cash_ps": net_cash_ps,
        "pv_stage": pv_stage,
        "pv_terminal": pv_terminal,
        "growth_path": path,
        "fcf_ps_base": fcf_ps0,
        "buyback_accretion_factor": accretion,
        "inputs": {
            "base_fcf": base_fcf, "shares": shares, "net_cash": net_cash,
            "explicit_growth": explicit_growth, "fade_years": fade_years,
            "terminal_growth": terminal_growth, "discount_rate": discount_rate,
            "buyback_shrink": buyback_shrink,
        },
    }


def _bisect(f, target, lo, hi, tol=1e-5, max_iter=200):
    """通用二分：解 f(x)=target，假定 f 在 [lo,hi] 单调递增。返回 (x, converged)。"""
    flo, fhi = f(lo), f(hi)
    if target < flo:
        return lo, False
    if target > fhi:
        return hi, False
    a, b = lo, hi
    for _ in range(max_iter):
        mid = (a + b) / 2.0
        fm = f(mid)
        if abs(fm - target) < tol or (b - a) < tol:
            return mid, True
        if fm < target:
            a = mid
        else:
            b = mid
    return (a + b) / 2.0, True


def implied_perpetual_growth(
    target_price: float, base_fcf: float, shares: float, net_cash: float,
    explicit_growth: list[float], fade_years: int, discount_rate: float,
    buyback_shrink: float = 0.0,
) -> dict:
    """
    反推 1(change 2 主口径)：固定一条合理的显式增长路径，解"隐含永续增长率"，
    使两段式每股价值==现价。对成熟公司终值占大头，这个数直接和 GDP(2.5-3%)对比最有意义。
    """
    def price_at(tg):
        return dcf_two_stage_per_share(
            base_fcf, shares, net_cash, explicit_growth, fade_years, tg,
            discount_rate, buyback_shrink,
        )["per_share_value"]

    hi = discount_rate - 0.005   # 永续增长上界(逼近折现率会发散)
    g, ok = _bisect(price_at, target_price, lo=-0.02, hi=hi)
    return {"implied_perpetual_growth": g, "converged": ok,
            "note": "现价隐含的永续增长率(显式路径固定)；>GDP(~3%)即偏贵"}


def implied_explicit_cagr(
    target_price: float, base_fcf: float, shares: float, net_cash: float,
    explicit_years: int, fade_years: int, terminal_growth: float, discount_rate: float,
    buyback_shrink: float = 0.0,
) -> dict:
    """
    反推 2(change 2 辅口径)：永续固定在 terminal_growth(如3%)，解"显式期恒定 CAGR"，
    再正常 fade 到永续。比旧单段式合理——溢价不再全压前5年，有 fade 缓冲。
    """
    def price_at(cagr):
        return dcf_two_stage_per_share(
            base_fcf, shares, net_cash, [cagr] * explicit_years, fade_years,
            terminal_growth, discount_rate, buyback_shrink,
        )["per_share_value"]

    g, ok = _bisect(price_at, target_price, lo=-0.20, hi=0.60)
    return {"implied_explicit_cagr": g, "converged": ok,
            "note": f"现价隐含的显式期({explicit_years}年)恒定增速，永续固定{terminal_growth}"}


def implied_constant_growth(
    target_price: float,
    base_fcf: float,
    discount_rate: float,
    terminal_growth: float,
    net_debt: float,
    shares_outstanding: float,
    years: int = 5,
    lo: float = -0.50,
    hi: float = 1.00,
    tol: float = 1e-4,
    max_iter: int = 200,
) -> dict:
    """
    反推 DCF (预期差的核心，原则 1)：
    解一个"未来 N 年恒定增长率 g"，使 DCF 每股价值 == 当前股价。
    回答的是"要支撑现价，市场隐含假设了多高的增长"。

    用二分法。返回隐含增长率 + 是否在搜索区间内收敛。
    """
    def price_at(g: float) -> float:
        v = dcf_value(
            base_fcf, [g] * years, discount_rate, terminal_growth,
            net_debt, shares_outstanding,
        )
        return v["per_share_value"]

    p_lo, p_hi = price_at(lo), price_at(hi)
    # 价格随 g 单调递增；若目标超出区间，老实报告越界，不假装收敛
    if target_price < p_lo:
        return {"implied_growth": lo, "converged": False, "note": "现价低于区间下界隐含价值"}
    if target_price > p_hi:
        return {"implied_growth": hi, "converged": False, "note": "现价高于区间上界隐含价值"}

    a, b = lo, hi
    for _ in range(max_iter):
        mid = (a + b) / 2.0
        pm = price_at(mid)
        if abs(pm - target_price) < tol or (b - a) < tol:
            return {"implied_growth": mid, "converged": True, "implied_price_check": pm}
        if pm < target_price:
            a = mid
        else:
            b = mid
    mid = (a + b) / 2.0
    return {"implied_growth": mid, "converged": True, "implied_price_check": price_at(mid)}
