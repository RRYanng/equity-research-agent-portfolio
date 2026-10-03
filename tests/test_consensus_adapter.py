"""
ConsensusAdapter 单测（Phase 5）—— 注入假 fetch，离线，不碰真网络。
守：正常返回 raw；无 key/失败 → None（上层据此判数据不足，绝不崩、绝不编）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.data.consensus_source import ConsensusAdapter

_TRENDS = [{"period": "2026-06-01", "strongBuy": 13, "buy": 24, "hold": 7, "sell": 0, "strongSell": 0}]
_SHORT = {"sharesShort": 45_000_000, "sharesShortPriorMonth": 40_000_000, "shortPercentOfFloat": 0.032}


def test_analyst_trends_returns_raw():
    a = ConsensusAdapter(rec_fetch=lambda t: _TRENDS, short_fetch=lambda t: _SHORT, cache=False)
    assert a.analyst_trends("AAPL") == _TRENDS


def test_short_interest_returns_raw():
    a = ConsensusAdapter(rec_fetch=lambda t: _TRENDS, short_fetch=lambda t: _SHORT, cache=False)
    assert a.short_interest("AAPL") == _SHORT


def test_fetch_failure_returns_none_no_crash():
    def boom(t):
        raise ConnectionError("down")
    a = ConsensusAdapter(rec_fetch=boom, short_fetch=boom, cache=False)
    assert a.analyst_trends("AAPL") is None
    assert a.short_interest("AAPL") is None
