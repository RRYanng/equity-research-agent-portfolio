"""
护栏单测（Phase 9 step①）：成本上限闸 + watchlist 残缺隔离。纯逻辑，零 LLM/零网络。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import llm, watchlist


# ─────────────── 成本上限"预调用闸" ───────────────
def test_estimate_scales_with_max_tokens():
    a = llm._estimate_next_cost(llm.SONNET, "sys", "user", max_tokens=1000)
    b = llm._estimate_next_cost(llm.SONNET, "sys", "user", max_tokens=4000)
    assert b > a > 0                       # 输出越多预估越高


def test_cost_gate_blocks_when_near_ceiling():
    llm.reset_usage()
    llm.set_cost_ceiling(0.30)
    llm._usage["est_cost_usd"] = 0.29       # 已逼近上限
    try:
        llm._cost_gate(llm.OPUS, "sys"*100, "user"*100, max_tokens=3000)  # 本次预估必然 > 0.01
    except llm.CostCeilingExceeded:
        llm.set_cost_ceiling(None)
        return
    llm.set_cost_ceiling(None)
    assert False, "逼近上限时必须抛 CostCeilingExceeded"


def test_cost_gate_allows_when_under():
    llm.reset_usage()
    llm.set_cost_ceiling(100.0)             # 上限很高
    llm._usage["est_cost_usd"] = 1.0
    llm._cost_gate(llm.SONNET, "sys", "user", max_tokens=500)   # 不应抛
    llm.set_cost_ceiling(None)


def test_no_ceiling_means_no_gate():
    llm.reset_usage()
    llm.set_cost_ceiling(None)
    llm._usage["est_cost_usd"] = 9999.0
    llm._cost_gate(llm.OPUS, "x", "y", max_tokens=4000)        # None=不限，不抛


def test_reset_usage_zeroes():
    llm._usage["est_cost_usd"] = 5.0
    llm._usage["calls"] = 9
    llm.reset_usage()
    assert llm._usage["est_cost_usd"] == 0.0 and llm._usage["calls"] == 0


def test_cost_ceiling_exceeded_is_not_generic_swallow_target():
    # 硬停信号必须是独立异常类型，便于熔断层放行(不被普通 except 吞)
    assert issubclass(llm.CostCeilingExceeded, Exception)


# ─────────────── watchlist 残缺隔离(防污染 diff 基线) ───────────────
def _fake_state(ticker, rating, ev):
    return SimpleNamespace(
        ticker=ticker,
        memo=SimpleNamespace(rating=rating, confidence="low",
                             expected_value_per_share=ev, valuation_method="dcf"),
        valuation_view=SimpleNamespace(implied_perpetual_growth=0.05,
                                       dcf_verdict="expensive", mult_verdict="fair"),
    )


def test_incomplete_run_excluded_from_diff_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "DB", tmp_path / "wl.sqlite")
    # 先写一条完整结论
    watchlist.record(_fake_state("X", "Hold", 100.0), incomplete=False)
    # 再写一条残缺结论(触及成本上限)
    watchlist.record(_fake_state("X", "INCOMPLETE", None), incomplete=True)
    # diff 基线必须仍是那条【完整】的 Hold/100，残缺的被排除
    last = watchlist.get_last("X")
    assert last is not None and last["rating"] == "Hold" and last["expected_value"] == 100.0


def test_only_incomplete_means_no_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "DB", tmp_path / "wl2.sqlite")
    watchlist.record(_fake_state("Y", "INCOMPLETE", None), incomplete=True)
    assert watchlist.get_last("Y") is None      # 只有残缺 → 无可用基线


# ─────────────── 节点 circuit breaker(Phase 9 ②) ───────────────
from proto.guardrails import breaker
from proto.llm import CostCeilingExceeded

def _fb(state, e):
    return {"view": "degraded"}


def test_breaker_passthrough_on_success():
    wrapped = breaker("n", lambda s: {"view": "ok"}, _fb)
    assert wrapped(None) == {"view": "ok"}      # 成功不动，无 node_failures


def test_breaker_degrades_on_normal_exception():
    def boom(s):
        raise ValueError("挂了")
    out = breaker("financial", boom, _fb)(None)
    assert out["view"] == "degraded"            # 返回降级视图
    assert out["node_failures"] == ["financial: ValueError: 挂了"]   # 留痕


def test_breaker_MUST_reraise_cost_ceiling():
    """关键边界：成本硬停信号绝不能被熔断吞掉——吞了那道成本闸就废了。"""
    def cost_stop(s):
        raise CostCeilingExceeded("触及上限")
    try:
        breaker("macro", cost_stop, _fb)(None)
    except CostCeilingExceeded:
        return                                  # ✓ 放行
    assert False, "熔断必须放行 CostCeilingExceeded，绝不能降级吞掉"


def test_breaker_reraises_keyboard_interrupt():
    def interrupt(s):
        raise KeyboardInterrupt()
    try:
        breaker("n", interrupt, _fb)(None)
    except KeyboardInterrupt:
        return
    assert False, "中断信号必须放行"


def test_three_mechanisms_orthogonal():
    """三道机制各管各的、不打架：成本硬停(异常) ≠ 熔断降级(返回值) ≠ 数据 fallback(None)。"""
    # 成本硬停：抛 CostCeilingExceeded（被 breaker 放行，不降级）
    assert issubclass(CostCeilingExceeded, Exception)
    # 熔断：普通异常 → 降级返回值（不抛）
    out = breaker("n", lambda s: (_ for _ in ()).throw(RuntimeError("x")), _fb)(None)
    assert "node_failures" in out and out["view"] == "degraded"
    # 数据 fallback：源失败返回 None（不抛、不降级视图）——由 adapter 层负责，这里仅声明边界
    from proto.data.multiples import FinnhubAdapter
    assert FinnhubAdapter(api_key=None).get_peer_multiples("X") is None
