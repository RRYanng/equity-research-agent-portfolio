"""DCF 单元测试 —— 验证算账正确，不碰 LLM/网络。"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.tools import dcf


def test_project_fcf_compounds():
    out = dcf.project_fcf(100.0, [0.10, 0.10])
    assert math.isclose(out[0], 110.0)
    assert math.isclose(out[1], 121.0)


def test_dcf_flat_zero_growth_known_value():
    # 零增长、折现率10%、永续增长0：终值 = FCF/(r) ，可手算校验
    base_fcf = 100.0
    r = 0.10
    out = dcf.dcf_value(
        base_fcf=base_fcf, growth_rates=[0.0] * 3, discount_rate=r,
        terminal_growth=0.0, net_debt=0.0, shares_outstanding=10.0,
    )
    # 显式期: 100/1.1 + 100/1.21 + 100/1.331
    pv_explicit = 100/1.1 + 100/1.21 + 100/1.331
    terminal_value = 100.0 / 0.10                     # 1000
    pv_terminal = terminal_value / (1.1 ** 3)
    ev = pv_explicit + pv_terminal
    assert math.isclose(out["enterprise_value"], ev, rel_tol=1e-9)
    assert math.isclose(out["per_share_value"], ev / 10.0, rel_tol=1e-9)


def test_dcf_subtracts_net_debt():
    no_debt = dcf.dcf_value(100, [0.05]*5, 0.09, 0.02, 0.0, 100)
    with_debt = dcf.dcf_value(100, [0.05]*5, 0.09, 0.02, 500.0, 100)
    assert with_debt["equity_value"] == no_debt["equity_value"] - 500.0


def test_dcf_rejects_divergent_terminal():
    try:
        dcf.dcf_value(100, [0.05], 0.03, 0.05, 0, 100)
    except ValueError:
        return
    assert False, "折现率<=永续增长应当报错"


def test_higher_discount_rate_lowers_value():
    low_r = dcf.dcf_value(100, [0.05]*5, 0.08, 0.02, 0, 100)["per_share_value"]
    high_r = dcf.dcf_value(100, [0.05]*5, 0.12, 0.02, 0, 100)["per_share_value"]
    assert high_r < low_r


def test_implied_growth_roundtrip():
    # 先用已知 g 算出价格，再反推，应当还原出同一个 g
    g_true = 0.08
    v = dcf.dcf_value(100, [g_true]*5, 0.10, 0.025, 0, 100)
    price = v["per_share_value"]
    out = dcf.implied_constant_growth(
        target_price=price, base_fcf=100, discount_rate=0.10,
        terminal_growth=0.025, net_debt=0, shares_outstanding=100, years=5,
    )
    assert out["converged"]
    assert math.isclose(out["implied_growth"], g_true, abs_tol=1e-3)


def test_sensitivity_grid_marks_invalid_cells():
    t = dcf.sensitivity_table(
        100, [0.05]*5, 0, 100,
        discount_rates=[0.03, 0.10],
        terminal_growths=[0.02, 0.05],
    )
    # r=0.03, tg=0.05 不合法 -> None
    assert t["values"][0][1] is None
    # r=0.10, tg=0.02 合法 -> 数字
    assert isinstance(t["values"][1][0], float)
