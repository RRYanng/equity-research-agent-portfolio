"""
macro_stage × FRED 集成红线测试（Phase 3）。

焊死项目最担心的洞——"LLM 尤其爱凭印象编宏观数字"：
  · 三指标只来自 FRED（stages._FRED），LLM 输出永远不写进 view.indicators。
  · 某指标 FRED 拿不到 → view.indicators 对应块 value=None（断言不是数字），
    且喂给 LLM 的 prompt 明确标"数据不足…不得臆造"，没有可被复述的假数字。
"""
import sys
from numbers import Number
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import stages
from proto.state import ResearchState


class _StubFredNone:
    """模拟 FRED 全拿不到（无 key / 网络失败）。"""
    def inflation(self):
        return {"value": None, "reason": "FRED 未返回 CPI"}
    def unemployment(self):
        return {"value": None, "reason": "FRED 未返回失业率"}
    def yield_curve(self):
        return {"value": None, "reason": "2Y 或 10Y 收益率数据不足"}


class _StubFredReal:
    """模拟 FRED 正常返回，且 LLM 试图'编'不同的数字——view 必须只认 FRED 的。"""
    def inflation(self):
        return {"value": 0.032, "as_of": "2026-05", "source": "FRED CPIAUCSL（YoY 自算）"}
    def unemployment(self):
        return {"value": 0.041, "as_of": "2026-06", "source": "FRED UNRATE"}
    def yield_curve(self):
        return {"dgs2": 0.046, "dgs10": 0.043, "spread": -0.003, "inverted": True,
                "as_of": "2026-06-30", "source": "FRED DGS2/DGS10（价差自算）"}


def _state():
    return ResearchState(ticker="TEST", raw_data={
        "as_of": "2026-06-30T00:00:00",
        "risk_free": {"rate": 0.043, "source": "yfinance ^TNX", "timestamp": "2026-06-30T00:00:00"},
    })


def test_missing_indicators_no_fabrication(monkeypatch):
    captured = {}

    def fake_llm(model, system, user, schema, *a, **k):
        captured["user"] = user
        # LLM 恶意"记得"一堆宏观数字——绝不能进 indicators
        return {"regime": "通胀约 9%、失业率 2%", "rate_path": "x",
                "liquidity": "x", "expectation_gap": "x", "marginal_change": "x"}

    monkeypatch.setattr(stages.llm, "call_structured", fake_llm)
    monkeypatch.setattr(stages, "_FRED", _StubFredNone(), raising=False)

    view = stages.macro_stage(_state())["macro_view"]

    for k in ("inflation", "unemployment", "yield_curve"):
        assert view.indicators[k]["value"] is None
        assert not isinstance(view.indicators[k]["value"], Number)   # 红线：不是数字

    u = captured["user"]
    assert "数据不足" in u and "不得臆造" in u
    assert u.count("数据不足") >= 3          # 三个指标行都标了数据不足，无假数字


def test_real_indicators_come_from_fred_not_llm(monkeypatch):
    def fake_llm(model, system, user, schema, *a, **k):
        return {"regime": "通胀约 9%", "rate_path": "x", "liquidity": "x",
                "expectation_gap": "x", "marginal_change": "x"}

    monkeypatch.setattr(stages.llm, "call_structured", fake_llm)
    monkeypatch.setattr(stages, "_FRED", _StubFredReal(), raising=False)

    view = stages.macro_stage(_state())["macro_view"]
    # 只认 FRED 的真值，不理会 LLM 嘴里的 "9%"
    assert view.indicators["inflation"]["value"] == 0.032
    assert view.indicators["unemployment"]["value"] == 0.041
    assert view.indicators["yield_curve"]["inverted"] is True
    assert view.indicators["yield_curve"]["spread"] == -0.003
