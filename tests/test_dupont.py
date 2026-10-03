"""杜邦 / 比率单元测试 —— 纯算账校验。"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.tools import dupont, ratios


def test_dupont_factors_multiply_to_roe():
    out = dupont.dupont_roe(
        net_income=100.0, revenue=1000.0, total_assets=2000.0, shareholders_equity=500.0,
    )
    assert math.isclose(out["net_margin"], 0.10)
    assert math.isclose(out["asset_turnover"], 0.50)
    assert math.isclose(out["equity_multiplier"], 4.0)
    # 三因子相乘 == 直接 ROE == 0.10*0.5*4 = 0.20
    assert math.isclose(out["roe"], 0.20)
    assert math.isclose(out["roe"], out["roe_direct_check"])


def test_dupont_rejects_zero_denominator():
    try:
        dupont.dupont_roe(100, 0, 2000, 500)
    except ValueError:
        return
    assert False, "营收为 0 应报错"


def test_margins_basic():
    m = ratios.margins(gross_profit=400, operating_income=300, net_income=200, revenue=1000)
    assert math.isclose(m["gross_margin"], 0.40)
    assert math.isclose(m["operating_margin"], 0.30)
    assert math.isclose(m["net_margin"], 0.20)


def test_margin_trend_bp():
    cur = {"net_margin": 0.21}
    pri = {"net_margin": 0.20}
    d = ratios.margin_trend(cur, pri)
    assert math.isclose(d["net_margin_delta_bp"], 100.0)  # +1pct = +100bp


def test_fcf_subtracts_capex():
    out = ratios.free_cash_flow(operating_cash_flow=1000, capex=-300)
    assert out["fcf"] == 700


def test_growth_quality_redflag():
    out = ratios.growth_quality(operating_cash_flow=50, net_income=100)
    assert out["ocf_to_ni"] == 0.5
    assert "红旗" in out["flag"]
