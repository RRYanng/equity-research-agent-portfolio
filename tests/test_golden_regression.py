"""
金标准回归集(#0) —— 把 AAPL/MSFT/C3.ai 暴露的结构性偏见固化成断言。

全部确定性、零 LLM、pytest 一键跑。每次改估值层前先跑这个集，有回归立刻报错。

设计：把"评级决策"从 LLM 里抽成纯函数(decide_rating)，这样"优质股 DCF 偏空但倍数中性→Hold"
这种端到端结论也能在不调用 API 的情况下被测住。
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.tools import dcf
from proto.tools.method_router import select_valuation_method
from proto.tools.comparables import comparables_valuation, rule_of_40, classify_valuation
from proto.tools.rating import decide_rating
from proto.stages import _normalize_scenarios


# ─────────────── #1 方法路由：负 FCF / 未盈利 必须关掉 DCF ───────────────
def test_c3ai_negative_fcf_routes_away_from_dcf():
    # C3.ai 画像：FCF 负、净利润负
    r = select_valuation_method(base_fcf=-44e6, net_income=-289e6)
    assert r["method"] == "multiples"
    assert r["dcf_eligible"] is False


def test_unprofitable_but_positive_fcf_not_high_confidence_dcf():
    # 正 FCF 但未盈利(如部分 SaaS)：DCF 不能当高置信主镜头
    r = select_valuation_method(base_fcf=200e6, net_income=-50e6)
    assert r["dcf_eligible"] is False or r["low_confidence"] is True


def test_quality_profitable_uses_dcf():
    r = select_valuation_method(base_fcf=98.7e9, net_income=112e9)
    assert r["method"] == "dcf"
    assert r["dcf_eligible"] is True


# ─────────────── #1 引擎硬闸：负 FCF 直接拒绝，绝不输出负内在价值 ───────────────
def test_dcf_engine_refuses_nonpositive_fcf():
    try:
        dcf.dcf_two_stage_per_share(
            base_fcf=-44e6, shares=142e6, net_cash=738e6,
            explicit_growth=[0.3]*5, fade_years=5, terminal_growth=0.03,
            discount_rate=0.157, buyback_shrink=0.0,
        )
    except ValueError:
        return
    assert False, "base_fcf<=0 时 DCF 引擎必须拒绝(防止负内在价值/符号反转)"


# ─────────────── 单调性：正 FCF 估值必须随显式增长单调上升 ───────────────
def test_positive_fcf_value_monotonic_in_growth():
    """守住 C3.ai 暴露的符号反转 bug：增长越高，正 FCF 标的估值必须越高。"""
    prev = None
    for g in [0.0, 0.03, 0.06, 0.10, 0.15]:
        v = dcf.dcf_two_stage_per_share(
            base_fcf=1000.0, shares=100.0, net_cash=0.0,
            explicit_growth=[g]*5, fade_years=5, terminal_growth=0.03,
            discount_rate=0.10, buyback_shrink=0.0,
        )["per_share_value"]
        if prev is not None:
            assert v > prev, f"估值未随增长单调上升: g={g} 时 {v} <= 前值 {prev}"
        prev = v


# ─────────────── #2 comparables 交叉镜头 ───────────────
def test_classify_valuation_bands():
    assert classify_valuation(current=10, fair_low=15, fair_high=25) == "cheap"
    assert classify_valuation(current=20, fair_low=15, fair_high=25) == "fair"
    assert classify_valuation(current=40, fair_low=15, fair_high=25) == "expensive"


def test_comparables_implied_value_band():
    out = comparables_valuation(
        eps=6.0, ebitda=140e9, sales=400e9, shares=15e9, net_debt=-34e9,  # 负=净现金
        fair_multiples={"pe": 28, "ev_ebitda": 18},
    )
    # P/E 隐含 = 6*28 = 168
    assert math.isclose(out["implied_values"]["pe"], 168.0, rel_tol=1e-6)
    # band 应覆盖各方法
    lo, hi = out["band"]
    assert lo <= out["implied_values"]["pe"] <= hi


def test_rule_of_40():
    assert rule_of_40(revenue_growth=0.25, fcf_margin=-0.11)["passes"] is False  # 25-11=14 <40
    assert rule_of_40(revenue_growth=0.30, fcf_margin=0.15)["passes"] is True    # 30+15=45 >=40


# ─────────────── #5 委员会分歧规则(核心修复) ───────────────
def test_quality_dcf_bearish_but_multiples_neutral_is_hold_not_confident_sell():
    """AAPL/MSFT 修复：DCF 偏空但倍数中性 → Hold + 低置信，绝不高置信 Sell。"""
    out = decide_rating(dcf_verdict="expensive", mult_verdict="fair", dcf_disabled=False)
    assert out["rating"] == "Hold"
    assert out["confidence"] == "low"


def test_both_lenses_bearish_is_confident_sell():
    out = decide_rating(dcf_verdict="expensive", mult_verdict="expensive", dcf_disabled=False)
    assert out["rating"] == "Sell"
    assert out["confidence"] == "high"


def test_both_lenses_cheap_is_buy():
    out = decide_rating(dcf_verdict="cheap", mult_verdict="cheap", dcf_disabled=False)
    assert out["rating"] == "Buy"


# ─────────────── 结构化输出健壮性(scenarios 形态多变) ───────────────
def test_normalize_scenarios_handles_list_and_dict():
    as_list = [{"name": "Bull", "explicit_growth": [0.1]}, {"name": "Base", "explicit_growth": [0.05]}]
    assert _normalize_scenarios(as_list) == as_list
    # dict 按名键 → 转 list，补上 name
    as_dict = {"Bull": {"explicit_growth": [0.1]}, "Base": {"explicit_growth": [0.05]}}
    out = _normalize_scenarios(as_dict)
    assert len(out) == 2 and all(s.get("name") for s in out)
    # 混入脏数据(字符串/无名)要被过滤掉，不崩
    assert _normalize_scenarios(["junk", {"explicit_growth": [0.1]}]) == []


def test_dcf_disabled_rating_comes_from_multiples():
    """C3.ai：DCF 关掉后，评级只能来自倍数/Rule-of-40，不能用 DCF 的负值。"""
    out = decide_rating(dcf_verdict=None, mult_verdict="expensive", dcf_disabled=True)
    assert out["rating"] == "Sell"
    assert out["confidence"] in ("low", "medium")
    assert "DCF" not in out["rating"]  # rating 是干净的标签
    assert "倍数" in out["basis"] or "multiples" in out["basis"].lower()
