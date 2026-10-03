"""
serializer 宏观块单测（FRED v2 · 前端卡片）。

_macro 只把 macro_stage 存好的 mv.indicators 拆成前端友好结构——纯展示，不算不编：
  · 无 indicators → None（前端不出卡片）。
  · 有值 → value/as_of/source 透传；缺 → reason 透传（前端画"数据不足"）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.state import MacroView
from web.api.serializers import _macro


def _mv(indicators):
    return MacroView(regime="x", risk_free_rate=0.043, equity_risk_premium=0.055,
                     base_discount_rate=0.098, rate_path="x", liquidity="x",
                     expectation_gap="x", marginal_change="x", indicators=indicators)


def test_macro_none_when_no_indicators():
    assert _macro(None) is None
    assert _macro(_mv({})) is None


def test_macro_exposes_three_indicators():
    ind = {
        "inflation": {"value": 0.0417, "as_of": "2026-05", "source": "FRED CPIAUCSL（YoY 自算）"},
        "unemployment": {"value": 0.042, "as_of": "2026-06", "source": "FRED UNRATE"},
        "yield_curve": {"dgs2": 0.0417, "dgs10": 0.0448, "spread": 0.0031, "inverted": False,
                        "as_of": "2026-07-01", "source": "FRED DGS2/DGS10（价差自算）"},
    }
    r = _macro(_mv(ind))
    assert r["inflation"]["value"] == 0.0417 and r["inflation"]["as_of"] == "2026-05"
    assert r["unemployment"]["value"] == 0.042 and r["unemployment"]["as_of"] == "2026-06"
    assert r["yield_curve"]["spread"] == 0.0031 and r["yield_curve"]["inverted"] is False
    assert "FRED" in r["inflation"]["source"]


def test_macro_passes_reason_when_data_insufficient():
    ind = {
        "inflation": {"value": None, "reason": "缺去年同月 CPI，无法算 YoY"},
        "unemployment": {"value": None, "reason": "FRED 未返回失业率"},
        "yield_curve": {"value": None, "reason": "2Y 或 10Y 收益率数据不足"},
    }
    r = _macro(_mv(ind))
    assert r["inflation"]["value"] is None and r["inflation"]["reason"]
    assert r["unemployment"]["value"] is None and r["unemployment"]["reason"]
    assert r["yield_curve"]["spread"] is None and r["yield_curve"]["reason"]   # 缺 → 无 spread
