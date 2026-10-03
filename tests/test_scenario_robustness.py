"""
回归：DCF eligible 但 scenarios 返空，绝不能静默退化成倍数分支/改变评级路径。

守住"静默走错、还给个体面错误结论"这个幽灵。纯确定性、零 LLM。
(新文件，不动现有 33 条金标准。)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from types import SimpleNamespace

from proto.tools import dcf
from proto.stages import (_fallback_scenarios, _ensure_three_scenarios, _resolve_rating,
                          _ensure_falsifiers, _FALLBACK_MARK)


# ── 1. 确定性兜底情景：永远产出完整的 Bull/Base/Bear，且单调 ──
def test_fallback_scenarios_complete_and_monotonic():
    sc = _fallback_scenarios(rev_growth=0.06)
    names = {s["name"] for s in sc}
    assert names == {"Bull", "Base", "Bear"}
    g = {s["name"]: s["explicit_growth"][0] for s in sc}
    assert g["Bull"] > g["Base"] > g["Bear"]      # 增长单调
    # 各情景的 DCF 每股价值也应单调(Bull>Base>Bear)，守住符号反转 bug
    def val(s):
        return dcf.dcf_two_stage_per_share(
            1e9, 1e8, 0.0, s["explicit_growth"], 5, s["terminal_growth"], 0.10, 0.0
        )["per_share_value"]
    by = {s["name"]: val(s) for s in sc}
    assert by["Bull"] > by["Base"] > by["Bear"]


def test_fallback_handles_missing_rev_growth():
    sc = _fallback_scenarios(rev_growth=None)   # 缺增速也不崩
    assert {s["name"] for s in sc} == {"Bull", "Base", "Bear"}


# ── 2. eligible 但 scenarios 返空/不全 → 兜底补齐，绝不留空 ──
def test_ensure_three_from_empty():
    out = _ensure_three_scenarios([], rev_growth=0.06)
    assert {s["name"] for s in out} == {"Bull", "Base", "Bear"}   # 空 → 兜底 3 套


def test_ensure_three_fills_partial():
    partial = [{"name": "Base", "explicit_growth": [0.07]*5, "terminal_growth": 0.028,
                "rationale": "LLM 给的"}]
    out = _ensure_three_scenarios(partial, rev_growth=0.06)
    assert {s["name"] for s in out} == {"Bull", "Base", "Bear"}   # 补齐缺的 Bull/Bear
    base = next(s for s in out if s["name"] == "Base")
    assert base["rationale"] == "LLM 给的"                         # 保留已有的合法情景


def test_ensure_three_keeps_full():
    full = [{"name": n, "explicit_growth": [0.05]*5, "terminal_growth": 0.03, "rationale": n}
            for n in ("Bull", "Base", "Bear")]
    out = _ensure_three_scenarios(full, rev_growth=0.06)
    assert len(out) == 3 and all(s["rationale"] in ("Bull", "Base", "Bear") for s in out)


# ── 3. 区分两种 None：DCF 失败(eligible) ≠ DCF 路由关闭(倍数法) ──
def test_resolve_rating_eligible_failed_is_hold_not_multiples_sell():
    """核心修复：eligible 但 dcf_verdict=None(计算失败) 绝不能当成倍数法 Sell。"""
    failed = _resolve_rating(dcf_disabled=False, dcf_verdict=None, mult_verdict="expensive")
    assert failed["rating"] == "Hold"            # 不是 Sell！
    assert failed["confidence"] == "low"


def test_resolve_rating_router_disabled_uses_multiples():
    """对照：路由主动关闭 DCF(C3.ai) 时，倍数=expensive 才给 Sell。"""
    disabled = _resolve_rating(dcf_disabled=True, dcf_verdict=None, mult_verdict="expensive")
    assert disabled["rating"] == "Sell"


def test_resolve_rating_two_nones_diverge():
    """同样是 dcf_verdict=None、mult=expensive，两种来源必须给出不同评级路径。"""
    failed = _resolve_rating(False, None, "expensive")    # 计算失败
    disabled = _resolve_rating(True, None, "expensive")   # 路由关闭
    assert failed["rating"] != disabled["rating"]         # Hold ≠ Sell


def test_resolve_rating_normal_paths_unchanged():
    # 两镜头一致 expensive → Sell high
    assert _resolve_rating(False, "expensive", "expensive")["rating"] == "Sell"
    # 分歧 → Hold low
    d = _resolve_rating(False, "expensive", "fair")
    assert d["rating"] == "Hold" and d["confidence"] == "low"


# ── falsifiers 守门(同 _ensure_three_scenarios 标准，长期守着) ──
def _state_with_vv(impl_perp=0.072):
    vv = SimpleNamespace(
        dcf_verdict="expensive", mult_verdict="fair", current_price=297.0,
        implied_perpetual_growth=impl_perp, implied_explicit_cagr=0.21,
        scenarios=[SimpleNamespace(name="Bear", per_share_value=105.0),
                   SimpleNamespace(name="Bull", per_share_value=170.0)],
    )
    return SimpleNamespace(valuation_view=vv)


def test_falsifiers_kept_when_llm_gives_enough():
    llm_f = ["A 事件证伪", "B 事件证伪", "C 事件证伪", "D 事件证伪"]
    out = _ensure_falsifiers(llm_f, _state_with_vv())
    assert out == llm_f                         # LLM 给够 → 原样用，不动


def test_falsifiers_fallback_when_empty():
    """LLM 返空 → 守门触发：兜底补到 ≥3，且每条都显式标注兜底来源。"""
    out = _ensure_falsifiers([], _state_with_vv())
    assert len(out) >= 3                        # 不静默放过
    assert all(_FALLBACK_MARK in f for f in out)   # 兜底来源如实标注，不假装是 LLM 原生


def test_falsifiers_fallback_fills_partial():
    out = _ensure_falsifiers(["真证伪1"], _state_with_vv())
    assert len(out) >= 3
    assert out[0] == "真证伪1"                   # 保留 LLM 给的
    assert any(_FALLBACK_MARK in f for f in out[1:])   # 缺的用标注过的兜底补


def test_fallback_falsifiers_use_real_data_not_fabricated():
    """关键边界：兜底只用已算出的真实数据(隐含增长7.2%、三情景价105–170)，绝不编造。"""
    out = _ensure_falsifiers([], _state_with_vv(impl_perp=0.072))
    blob = " ".join(out)
    assert "7.2%" in blob                       # 隐含永续增长来自已算值
    assert "105" in blob and "170" in blob      # 三情景价来自已算值


def test_falsifiers_fallback_works_without_valuation():
    """PRE_IPO/数据不足(vv 缺失)也能凑足 ≥3 条数据可得性类证伪，不涉任何编造数字。"""
    out = _ensure_falsifiers([], SimpleNamespace(valuation_view=None))
    assert len(out) >= 3 and all(_FALLBACK_MARK in f for f in out)
