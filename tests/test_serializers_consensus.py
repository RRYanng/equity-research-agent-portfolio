"""serializer 市场共识块单测（Phase 5）。纯展示拆分，缺 → reason 透传，绝不编。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.api.serializers import _consensus


class _S:
    def __init__(self, mc): self.market_consensus = mc


def test_consensus_none_when_empty():
    assert _consensus(_S({})) is None
    assert _consensus(_S(None)) is None


def test_consensus_exposes_signals():
    mc = {
        "analyst": {"direction": "转多", "latest": {"buy_side": 37, "total": 44},
                    "buy_side_share_change": 0.05, "as_of": "2026-06", "source": "Finnhub recommendation_trends"},
        "short": {"direction": "↑", "pct_of_float": 0.032, "mom_change": 0.125,
                  "as_of": "2025-06-15", "source": "yfinance short interest"},
    }
    r = _consensus(_S(mc))
    assert r["analyst"]["direction"] == "转多" and r["analyst"]["as_of"] == "2026-06"
    assert r["short"]["mom_change"] == 0.125 and "yfinance" in r["short"]["source"]


def test_consensus_passes_reason_when_insufficient():
    mc = {"analyst": {"value": None, "reason": "不足两月"},
          "short": {"value": None, "reason": "缺短仓字段"}}
    r = _consensus(_S(mc))
    assert r["analyst"]["direction"] is None and r["analyst"]["reason"]
    assert r["short"]["mom_change"] is None and r["short"]["reason"]
