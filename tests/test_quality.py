"""
公司质量纯函数单测（第一层质量增量）。

守死项目零伪造头号原则：
  · 字段齐全 → 算出精确数字（断言具体数值）。
  · 任一关键字段缺失 → 返回 {"value": None, "reason": ...}，**绝不返回一个编造的数字**。
  · 负基数（上期 ≤0）的同比增速 → 标"不适用"，不硬算出误导性百分比。
纯函数、零 LLM、零网络。不触碰冻结的 tools/ 与 88 回归。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import quality


# ─────────────── 盈利能力：ROIC / ROE ───────────────
def test_roic_exact():
    # 营业利润 200，税 30/税前 150 → 税率 0.2 → NOPAT 160；投入资本=债 400+权益 600=1000 → 0.16
    r = quality.roic(operating_income=200, tax_provision=30, pretax_income=150,
                     total_debt=400, shareholders_equity=600)
    assert abs(r["value"] - 0.16) < 1e-9
    assert abs(r["tax_rate"] - 0.2) < 1e-9
    assert r["source_kind"] == "computed"


def test_roic_loss_period_no_tax_shield():
    # 亏损期(税前≤0)：税率视为 0，NOPAT=营业利润，ROIC 如实为负，不掩盖
    r = quality.roic(operating_income=-100, tax_provision=0, pretax_income=-120,
                     total_debt=400, shareholders_equity=600)
    assert r["value"] < 0
    assert r["tax_rate"] == 0.0


def test_roe_exact():
    r = quality.roe(net_income=120, shareholders_equity=600)
    assert abs(r["value"] - 0.20) < 1e-9
    assert r["source_kind"] == "computed"


# ─────────────── 成长趋势：同比 + 加速/放缓 ───────────────
def test_yoy_growth_exact():
    assert abs(quality.yoy_growth(110, 100)["value"] - 0.10) < 1e-9


def test_growth_trend_accelerating():
    # 本期增速 120/100-1=20% > 上期 100/90-1≈11.1% → 加速
    t = quality.growth_trend(current=120, prior=100, prior2=90)
    assert abs(t["latest_growth"] - 0.20) < 1e-9
    assert abs(t["prior_growth"] - (100/90 - 1)) < 1e-9
    assert t["trend"] == "加速"


def test_growth_trend_decelerating():
    # 本期 105/100-1=5% < 上期 100/80-1=25% → 放缓
    t = quality.growth_trend(current=105, prior=100, prior2=80)
    assert t["trend"] == "放缓"


# ─────────────── 财务健康：负债比 / 净负债·EBITDA / 短债覆盖 ───────────────
def test_debt_to_assets_exact():
    # 总负债 = 总资产 1000 - 权益 400 = 600 → 0.60
    r = quality.debt_to_assets(total_assets=1000, shareholders_equity=400)
    assert abs(r["value"] - 0.60) < 1e-9


def test_net_debt_to_ebitda_exact():
    r = quality.net_debt_to_ebitda(net_debt=300, ebitda=150)
    assert abs(r["value"] - 2.0) < 1e-9


def test_short_term_debt_coverage_exact():
    r = quality.short_term_debt_coverage(cash=200, current_debt=100)
    assert abs(r["value"] - 2.0) < 1e-9


# ─────────────── 边界：缺字段 → None+reason，断言不是数字（零伪造守门）───────────────
def test_roic_missing_tax_returns_na_not_a_number():
    r = quality.roic(operating_income=200, tax_provision=None, pretax_income=150,
                     total_debt=400, shareholders_equity=600)
    assert r["value"] is None
    assert not isinstance(r["value"], (int, float))   # 绝不编一个数字填空
    assert r["reason"]                                  # 必须说明为什么不足


def test_roe_zero_equity_returns_na():
    r = quality.roe(net_income=120, shareholders_equity=0)
    assert r["value"] is None and r["reason"]


def test_net_debt_to_ebitda_missing_or_nonpositive_ebitda_na():
    assert quality.net_debt_to_ebitda(net_debt=300, ebitda=None)["value"] is None
    r = quality.net_debt_to_ebitda(net_debt=300, ebitda=0)     # EBITDA 非正不适用
    assert r["value"] is None and r["reason"]


def test_short_term_coverage_missing_current_debt_na():
    r = quality.short_term_debt_coverage(cash=200, current_debt=None)
    assert r["value"] is None and not isinstance(r["value"], (int, float))


def test_debt_to_assets_missing_field_na():
    r = quality.debt_to_assets(total_assets=None, shareholders_equity=400)
    assert r["value"] is None and r["reason"]


# ─────────────── 负基数：增速必须标"不适用"，绝不硬算 ───────────────
def test_yoy_growth_negative_base_not_applicable():
    # 上期净利为负 → 同比增速无意义，必须标不适用，不能返回一个百分比
    r = quality.yoy_growth(current=100, prior=-50)
    assert r["value"] is None
    assert not isinstance(r["value"], (int, float))
    assert "不适用" in r["reason"] or "基数" in r["reason"]


def test_growth_trend_with_negative_prior2_is_insufficient():
    # BMNR 式：净利上上期为负 → 上期增速算不出 → 趋势数据不足，无编造
    t = quality.growth_trend(current=100, prior=50, prior2=-30)
    assert t["trend"] == "数据不足"
    assert t["prior_growth"] is None


# ─────────────── 汇总器：缺字段的项各自降级，不连坐、不编造 ───────────────
def test_company_quality_partial_fields_degrade_independently():
    # 模拟"旧缓存"：有当期资产负债表，但缺 ebitda / prior2 / 税
    f = {
        "operating_income": 200, "net_income": 120, "revenue": 1000,
        "revenue_prior": 900, "net_income_prior": 100,
        "total_assets": 1000, "shareholders_equity": 600, "total_debt": 400,
        "cash": 200,
        # 缺：tax_provision, pretax_income, ebitda, current_debt, revenue_prior2, net_income_prior2
    }
    q = quality.company_quality(f, net_debt=200)
    assert q["roe"]["value"] is not None                    # 能算的照算
    assert q["debt_to_assets"]["value"] is not None
    assert q["roic"]["value"] is None                       # 缺税 → 不足
    assert q["net_debt_to_ebitda"]["value"] is None         # 缺 EBITDA → 不足
    assert q["revenue_trend"]["trend"] == "数据不足"         # 缺 prior2 → 趋势不足
    # 没有任何一项被编出数字
    for key in ("roic", "net_debt_to_ebitda", "short_term_debt_coverage"):
        assert q[key]["value"] is None
