"""
市场共识信号纯函数（Phase 5 · 诚实版 Sentiment）—— LLM-free、零网络。

**不是"情绪分"**：不让 LLM 读新闻编一个不可溯源的分数（那违反原则③④⑤）。这里只用硬数据：
  · analyst_trend：Finnhub recommendation_trends 的纯计数 + **buy-side 占比月环比**方向
    （透明规则 (strongBuy+buy)/total 环比 ↑→转多 / ↓→转空 / 持平，可复述、非打分）。
  · short_interest：yfinance 短仓硬数字 + 环比方向。

定位：**仅作预期差的对照**（共识看多 vs 三方镜头判偏贵 = 背离本身是信息），
绝不驱动评级——由 consensus_stage 跑在 committee 之后 + 不进任何 prompt 三重保证。

零伪造红线：任一必要字段缺 → {"value": None, "reason": ...}，绝不编。
"""
from __future__ import annotations

import datetime as dt

_BUCKETS = ("strongBuy", "buy", "hold", "sell", "strongSell")


def _na(reason: str) -> dict:
    return {"value": None, "reason": reason}


def _month(period: str) -> str:
    """'2026-06-01' → '2026-06'（所属月）。"""
    return period[:7] if period and len(period) >= 7 else period


def _dist(row: dict) -> dict:
    counts = {b: int(row.get(b) or 0) for b in _BUCKETS}
    total = sum(counts.values())
    buy_side = counts["strongBuy"] + counts["buy"]
    counts["total"] = total
    counts["buy_side"] = buy_side
    counts["buy_side_share"] = round(buy_side / total, 4) if total else None
    return counts


def analyst_trend(trends) -> dict:
    """分析师评级分布 + buy-side 占比月环比方向。不足两月/无有效计数 → 数据不足。"""
    rows = list(trends or [])
    if len(rows) < 2:
        return _na("分析师评级趋势不足两月，无法算环比")
    latest, prior = _dist(rows[0]), _dist(rows[1])
    if latest["buy_side_share"] is None or prior["buy_side_share"] is None:
        return _na("某月评级总数为 0，无法算 buy-side 占比")
    change = round(latest["buy_side_share"] - prior["buy_side_share"], 4)
    direction = "转多" if change > 0 else "转空" if change < 0 else "持平"
    return {
        "latest": latest, "prior": prior,
        "buy_side_share_change": change, "direction": direction,
        "as_of": _month(rows[0].get("period")),
        "source": "Finnhub recommendation_trends",
    }


def short_interest(info: dict) -> dict:
    """短仓比例 + 环比方向（硬数字）。缺 sharesShort/上月短仓 → 数据不足。"""
    cur = (info or {}).get("sharesShort")
    prior = (info or {}).get("sharesShortPriorMonth")
    if cur is None or prior in (None, 0):
        return _na("缺短仓 / 上月短仓字段，无法算环比")
    mom = round(cur / prior - 1, 4)
    direction = "↑" if mom > 0 else "↓" if mom < 0 else "持平"
    ts = (info or {}).get("dateShortInterest")
    as_of = None
    if isinstance(ts, (int, float)):
        as_of = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
    return {
        "pct_of_float": info.get("shortPercentOfFloat"),
        "shares_short": cur, "shares_short_prior": prior,
        "mom_change": mom, "direction": direction,
        "as_of": as_of, "source": "yfinance short interest",
    }
