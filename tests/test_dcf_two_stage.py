"""两段式/每股 DCF + 反推求解器的单元测试。"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.tools import dcf


def test_growth_path_fades_to_terminal():
    path = dcf._growth_path([0.08, 0.08, 0.07, 0.06, 0.06], fade_years=5, terminal_growth=0.03)
    assert len(path) == 10
    assert math.isclose(path[4], 0.06)          # 最后一个显式期
    assert math.isclose(path[-1], 0.03)         # fade 终点 = terminal
    # 过渡期单调下降
    fade = path[5:]
    assert all(fade[i] >= fade[i + 1] for i in range(len(fade) - 1))


def test_buyback_accretion_raises_per_share_value():
    common = dict(base_fcf=1000.0, shares=100.0, net_cash=0.0,
                  explicit_growth=[0.05]*5, fade_years=5, terminal_growth=0.03,
                  discount_rate=0.10)
    no_buyback = dcf.dcf_two_stage_per_share(**common, buyback_shrink=0.0)["per_share_value"]
    with_buyback = dcf.dcf_two_stage_per_share(**common, buyback_shrink=0.03)["per_share_value"]
    assert with_buyback > no_buyback            # 缩股抬高每股价值


def test_net_cash_adds_per_share():
    common = dict(base_fcf=1000.0, shares=100.0, explicit_growth=[0.05]*5,
                  fade_years=5, terminal_growth=0.03, discount_rate=0.10, buyback_shrink=0.0)
    base = dcf.dcf_two_stage_per_share(**common, net_cash=0.0)["per_share_value"]
    plus = dcf.dcf_two_stage_per_share(**common, net_cash=1000.0)["per_share_value"]
    assert math.isclose(plus - base, 1000.0 / 100.0)   # 净现金按面值/股加上


def test_two_stage_rejects_divergent_terminal():
    try:
        dcf.dcf_two_stage_per_share(1000, 100, 0, [0.05]*5, 5, 0.05, 0.04)
    except ValueError:
        return
    assert False, "折现率<=永续增长应报错"


def test_implied_perpetual_growth_roundtrip():
    args = dict(base_fcf=1000.0, shares=100.0, net_cash=0.0,
                explicit_growth=[0.06]*5, fade_years=5, discount_rate=0.10, buyback_shrink=0.02)
    tg_true = 0.028
    price = dcf.dcf_two_stage_per_share(terminal_growth=tg_true, **args)["per_share_value"]
    out = dcf.implied_perpetual_growth(target_price=price, **args)
    assert out["converged"]
    assert math.isclose(out["implied_perpetual_growth"], tg_true, abs_tol=1e-3)


def test_implied_explicit_cagr_roundtrip():
    args = dict(base_fcf=1000.0, shares=100.0, net_cash=0.0, explicit_years=5,
                fade_years=5, terminal_growth=0.03, discount_rate=0.10, buyback_shrink=0.02)
    cagr_true = 0.12
    price = dcf.dcf_two_stage_per_share(
        base_fcf=1000.0, shares=100.0, net_cash=0.0, explicit_growth=[cagr_true]*5,
        fade_years=5, terminal_growth=0.03, discount_rate=0.10, buyback_shrink=0.02,
    )["per_share_value"]
    out = dcf.implied_explicit_cagr(target_price=price, **args)
    assert out["converged"]
    assert math.isclose(out["implied_explicit_cagr"], cagr_true, abs_tol=1e-3)


def test_higher_discount_lowers_two_stage_value():
    common = dict(base_fcf=1000.0, shares=100.0, net_cash=0.0, explicit_growth=[0.06]*5,
                  fade_years=5, terminal_growth=0.03, buyback_shrink=0.0)
    lo = dcf.dcf_two_stage_per_share(**common, discount_rate=0.08)["per_share_value"]
    hi = dcf.dcf_two_stage_per_share(**common, discount_rate=0.12)["per_share_value"]
    assert hi < lo
