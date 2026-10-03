"""
NAV(资产净值)估值 —— 纯函数，零 LLM、零网络。

针对"资产远大于经营"的壳类公司(v1: BTC/ETH 加密国库股)：算出每股 NAV，
呈现"现价相对 NAV 是溢价还是折价"。NAV 不是目标价——是"今天按市值清算每股资产值多少"。

刻意不放进 tools/(冻结，含 method_router)；新独立纯函数模块。
持仓量/币价/现金/负债全部是外部真实数据(由 stage 注入)，LLM 绝不参与算或猜。

零伪造红线(守死)：
  · 任一关键输入缺失 → 返回 {"value": None, "reason": ...}，绝不返回数字。
  · 口径最严：现金/总债务任一缺失 → 整块"数据不足"，绝不给"未扣负债的毛 NAV"(会高估、误导)。
  · 持仓量缺失 → 数据不足，绝不用 LLM 记忆补持仓数。
"""
from __future__ import annotations

_CK = "computed"

# 经营对资产的占比阈值：营收/总资产 < 此值 → 经营相对资产微不足道 → 疑似资产持有型
_ASSET_HEAVY_REV_TO_ASSETS = 0.05

# NAV 该施加的折价类型(静态定性标注，非 LLM、非伪精确数字)
DISCOUNT_NOTES = [
    "执行力折价：管理层能否持续增厚每股币/资产，存不确定性",
    "流动性折价：大额持仓清算可能冲击价格，难按市价全额变现",
    "资产价格波动风险：NAV 随币价/持股价实时波动，非稳定锚",
    "注：国库股常见相对 NAV 溢价，反映市场对持续增持/杠杆增厚每股币的预期；折价则反映上述风险",
]


def _na(reason: str) -> dict:
    return {"value": None, "reason": reason, "source_kind": _CK}


def crypto_holdings_value(positions: list) -> dict:
    """
    多币持仓市值求和 = Σ(每币持仓数 × 该币价)。一家公司可同时持多种币(如 BMNR 持 ETH+BTC)，
    必须全部计入。任一币的持仓数或币价缺失 → 整体"数据不足"(value=None)，
    **绝不漏算那一币导致低估**(低估 NAV 同样误导)。
    """
    breakdown = []
    total = 0.0
    for p in positions or []:
        coin, count, price = p.get("coin"), p.get("count"), p.get("price")
        if count is None:
            return _na(f"缺持仓量({coin})：未取得真实持仓，绝不估算、也不漏算")
        if price is None:
            return _na(f"缺币价({coin})：未取得实时行情")
        v = count * price
        total += v
        breakdown.append({"coin": coin, "count": count, "price": price, "value": v})
    if not breakdown:
        return _na("无任何加密持仓记录")
    return {"value": total, "breakdown": breakdown, "source_kind": _CK,
            "fn": "proto.nav.crypto_holdings_value"}


def nav_per_share(crypto_value, cash, total_debt, shares, current_price=None) -> dict:
    """
    每股 NAV = (加密总市值 + 现金 − 总债务) / 股数。crypto_value 为多币求和后的总市值。
    溢价折价 = 现价/NAV − 1(缺现价则 None，但 NAV 本身仍算)。
    crypto_value / cash / total_debt / shares 任一缺失 → 数据不足(最严口径)。
    """
    if crypto_value is None:
        return _na("缺加密持仓市值(持仓量或币价没拿全)：绝不补一个数字")
    if cash is None:
        return _na("缺现金(cash)：无法净额计 NAV，不给未扣项的毛 NAV")
    if total_debt is None:
        return _na("缺总债务(total_debt)：无法净额计 NAV，不给未扣负债的毛 NAV")
    if not shares:                      # None 或 0
        return _na("缺股数(shares)或为 0：每股 NAV 无法计算")

    net_asset_value = crypto_value + cash - total_debt
    nav_ps = net_asset_value / shares
    premium_discount = (current_price / nav_ps - 1) if (current_price and nav_ps) else None
    return {
        "value": nav_ps, "crypto_value": crypto_value, "net_asset_value": net_asset_value,
        "cash": cash, "total_debt": total_debt, "shares": shares,
        "current_price": current_price, "premium_discount": premium_discount,
        "source_kind": _CK, "fn": "proto.nav.nav_per_share",
    }


def classify_asset_holder(ticker, fundamentals: dict, treasury_hit) -> dict:
    """
    确定性判定(不靠 LLM)：是不是资产持有型 / 哪一类 / 能不能算 NAV。
      1) ticker 命中 CoinGecko 国库清单(treasury_hit 非空) → crypto_treasury，可算 NAV。
      2) 否则但"营收对总资产微不足道"(资产远大于经营) → suspected_asset_holder，
         **NAV 不适用**(拿不到持仓明细，绝不硬算)。
      3) 否则 → operating(经营型)，不出 NAV 区块。
    treasury_hit 由数据层注入(持仓记录或 None)，使本函数纯粹、可测、无网络。
    """
    if treasury_hit:                    # 非空(dict 或 list of 持仓记录)→ 命中国库清单
        coins = None
        if isinstance(treasury_hit, list):
            coins = "/".join(str(h.get("coin")) for h in treasury_hit)
        elif isinstance(treasury_hit, dict):
            coins = str(treasury_hit.get("coin"))
        return {"type": "crypto_treasury", "nav_applicable": True, "coin": coins,
                "reason": f"命中 CoinGecko 国库清单({coins})，持仓可得，按 NAV 估值"}

    rev = (fundamentals or {}).get("revenue")
    assets = (fundamentals or {}).get("total_assets")
    if rev is not None and assets and assets > 0 and (rev / assets) < _ASSET_HEAVY_REV_TO_ASSETS:
        return {"type": "suspected_asset_holder", "nav_applicable": False,
                "reason": "资产远大于经营，疑似资产持有型；但无法获取持仓明细 → NAV 不适用(数据不足，不硬算)"}

    return {"type": "operating", "nav_applicable": False,
            "reason": "经营型公司，按经营法(DCF/倍数)估值，不出 NAV 区块"}
