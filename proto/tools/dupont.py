"""
杜邦 ROE 三因子拆解 —— 纯函数，零 LLM (README.md 原则 3)。

ROE = 净利率 × 资产周转率 × 权益乘数
    = (净利润/营收) × (营收/总资产) × (总资产/股东权益)

把 ROE 拆成"赚钱能力 / 运营效率 / 杠杆"三块，让 LLM 能解读
"这家公司的高 ROE 是靠利润率、周转、还是加杠杆撑起来的"。
"""
from __future__ import annotations


def dupont_roe(
    net_income: float,
    revenue: float,
    total_assets: float,
    shareholders_equity: float,
) -> dict:
    """返回三因子 + 相乘得到的 ROE + 直接算的 ROE(两者应一致，互为校验)。"""
    if revenue == 0 or total_assets == 0 or shareholders_equity == 0:
        raise ValueError("revenue / total_assets / shareholders_equity 不能为 0")

    net_margin = net_income / revenue
    asset_turnover = revenue / total_assets
    equity_multiplier = total_assets / shareholders_equity

    roe_decomposed = net_margin * asset_turnover * equity_multiplier
    roe_direct = net_income / shareholders_equity

    return {
        "net_margin": net_margin,
        "asset_turnover": asset_turnover,
        "equity_multiplier": equity_multiplier,
        "roe": roe_decomposed,
        "roe_direct_check": roe_direct,
        "inputs": {
            "net_income": net_income,
            "revenue": revenue,
            "total_assets": total_assets,
            "shareholders_equity": shareholders_equity,
        },
    }
