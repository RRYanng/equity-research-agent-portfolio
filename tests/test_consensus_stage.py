"""
consensus_stage 集成测（Phase 5）—— 守诚实命脉：**节点内零 LLM**、纯展示。

① stub adapter → market_consensus 正确填充。
② 关键：monkeypatch llm.call_structured 令其一旦被调就炸 → 证明 consensus_stage **不碰任何 LLM**。
③ 数据缺 → 两信号均数据不足，绝不编。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import stages
from proto.state import ResearchState

_TRENDS = [
    {"period": "2026-06-01", "strongBuy": 13, "buy": 24, "hold": 7, "sell": 0, "strongSell": 0},
    {"period": "2026-05-01", "strongBuy": 12, "buy": 22, "hold": 8, "sell": 1, "strongSell": 0},
]
_SHORT = {"sharesShort": 45_000_000, "sharesShortPriorMonth": 40_000_000,
          "shortPercentOfFloat": 0.032, "dateShortInterest": 1_750_000_000}


class _StubOK:
    def analyst_trends(self, t): return _TRENDS
    def short_interest(self, t): return _SHORT


class _StubNone:
    def analyst_trends(self, t): return None
    def short_interest(self, t): return None


def _no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("consensus_stage 绝不该调用 LLM（诚实命脉）")
    monkeypatch.setattr(stages.llm, "call_structured", boom)


def test_consensus_stage_llm_free_and_populates(monkeypatch):
    _no_llm(monkeypatch)                                   # 一旦调 LLM 就炸
    monkeypatch.setattr(stages, "_CONSENSUS", _StubOK(), raising=False)
    mc = stages.consensus_stage(ResearchState(ticker="AAPL", raw_data={}))["market_consensus"]
    assert mc["analyst"]["direction"] == "转多"
    assert mc["analyst"]["latest"]["buy_side"] == 37
    assert mc["short"]["direction"] == "↑"
    assert abs(mc["short"]["mom_change"] - 0.125) < 1e-9


def test_consensus_stage_data_insufficient(monkeypatch):
    _no_llm(monkeypatch)
    monkeypatch.setattr(stages, "_CONSENSUS", _StubNone(), raising=False)
    mc = stages.consensus_stage(ResearchState(ticker="X", raw_data={}))["market_consensus"]
    assert mc["analyst"]["value"] is None and mc["analyst"]["reason"]
    assert mc["short"]["value"] is None and mc["short"]["reason"]
