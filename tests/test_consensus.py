"""
市场共识信号纯函数单测（Phase 5 · 诚实版 Sentiment）—— LLM-free、零网络。

这不是"情绪分"：分析师用纯计数 + buy-side 占比月环比（透明规则、可复述），短仓用硬数字 + 环比。
守死：任一必要字段缺 → {"value": None, "reason": ...}，绝不编。方向是确定性规则，非 LLM 打分。
"""
import sys
from numbers import Number
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import consensus


# ① 分析师趋势正常：buy-side 占比环比 ↑ → 转多
def test_analyst_trend_bullish_shift():
    trends = [
        {"period": "2026-06-01", "strongBuy": 13, "buy": 24, "hold": 7, "sell": 0, "strongSell": 0},
        {"period": "2026-05-01", "strongBuy": 12, "buy": 22, "hold": 8, "sell": 1, "strongSell": 0},
    ]
    r = consensus.analyst_trend(trends)
    assert r["direction"] == "转多"
    assert r["latest"]["buy_side"] == 37 and r["latest"]["total"] == 44
    assert r["as_of"] == "2026-06"
    assert r["buy_side_share_change"] > 0
    assert "Finnhub" in r["source"]


# ② 不足两月 → 数据不足，绝不返回数字
def test_analyst_trend_insufficient_months():
    r = consensus.analyst_trend([{"period": "2026-06-01", "strongBuy": 13, "buy": 24,
                                  "hold": 7, "sell": 0, "strongSell": 0}])
    assert r["value"] is None
    assert not isinstance(r["value"], Number)
    assert "reason" in r


# ③ 分析师占比环比持平 → 持平（透明规则边界）
def test_analyst_trend_flat():
    trends = [
        {"period": "2026-06-01", "strongBuy": 10, "buy": 10, "hold": 5, "sell": 5, "strongSell": 0},
        {"period": "2026-05-01", "strongBuy": 8, "buy": 12, "hold": 5, "sell": 5, "strongSell": 0},
    ]  # 两月 buy_side 均 20/30
    assert consensus.analyst_trend(trends)["direction"] == "持平"


# ④ 短仓正常：环比 + 方向（硬数字，零 LLM）
def test_short_interest_mom_up():
    info = {"sharesShort": 45_000_000, "sharesShortPriorMonth": 40_000_000,
            "shortPercentOfFloat": 0.032, "dateShortInterest": 1_750_000_000}
    r = consensus.short_interest(info)
    assert abs(r["mom_change"] - 0.125) < 1e-9        # 45/40 − 1
    assert r["direction"] == "↑"
    assert r["pct_of_float"] == 0.032
    assert "yfinance" in r["source"]


# ⑤ 短仓缺字段 → 数据不足，绝不编
def test_short_interest_missing_field():
    r = consensus.short_interest({"sharesShort": 45_000_000, "sharesShortPriorMonth": None,
                                  "shortPercentOfFloat": 0.032})
    assert r["value"] is None
    assert not isinstance(r["value"], Number)
    assert "reason" in r
