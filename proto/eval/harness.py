"""
评测 harness（Phase 9 ③）：跑 5 案例打 rubric 质量分。

两种模式：
 · replay(默认)：重放合成的 LLM/数据，**快、免费、确定性**。守"分析质量逻辑"有没有退步。
 · live：真跑(花钱)。守 LLM 漂移。

录制：`python -m proto.eval.harness --record`(一次性 live，建 fixture)。
评测：`python -m proto.eval.harness`(默认 replay) / `--live`。

与单元测试的分工：回归(pytest) 守【代码逻辑】(纯函数/规则)；本 harness 守【端到端分析质量】
(评级方向/分流/无编造)。回归快而细，评测慢而全，互补。
"""
from __future__ import annotations

import sys
import json
import hashlib
from pathlib import Path

from .. import llm, stages
from ..graph import build_graph, RECURSION_LIMIT
from ..state import ResearchState, DataTier
from ..data.adapter import DataAdapter
from .cases import CASES

_FIX = Path(__file__).resolve().parent / "fixtures"
_FIX.mkdir(exist_ok=True)


def _key(model, system, user):
    return hashlib.sha256(f"{model}\x00{system}\x00{user}".encode()).hexdigest()


def _fixture_file(ticker):
    return _FIX / f"{ticker}.json"


# ───────────────────────── 录制(live) ─────────────────────────
def record(ticker: str):
    """live 跑一次，捕获 raw_data + finnhub + 所有 LLM 响应，存 fixture。"""
    llm.set_cost_ceiling(None); llm.reset_usage()
    cache = {"raw_data": None, "finnhub": {}, "llm": {}, "fred": {}}

    orig_llm = llm.call_structured
    def rec_llm(model, system, user, schema, tool_name="emit", max_tokens=2000):
        out = orig_llm(model, system, user, schema, tool_name, max_tokens)
        cache["llm"][_key(model, system, user)] = out
        return out
    orig_fh = stages._FINNHUB.get_peer_multiples
    def rec_fh(tk):
        r = orig_fh(tk)
        cache["finnhub"][tk] = r
        return r

    llm.call_structured = rec_llm
    stages._FINNHUB.get_peer_multiples = rec_fh
    try:
        app = build_graph()
        final = app.invoke(ResearchState(ticker=ticker), config={"recursion_limit": RECURSION_LIMIT})
        state = ResearchState.model_validate(final) if isinstance(final, dict) else final
        cache["raw_data"] = state.raw_data
        # FRED 三指标：直接取 macro_view 里记录的值(macro_stage 已确定性取好)，replay 回放
        cache["fred"] = (state.macro_view.indicators if state.macro_view else {}) or {}
    finally:
        llm.call_structured = orig_llm
        stages._FINNHUB.get_peer_multiples = orig_fh
    destination = Path(__file__).resolve().parents[2] / "data_cache" / "eval_recordings" / f"{ticker}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(cache, ensure_ascii=False, default=str))
    print(f"  recorded {ticker}: llm={len(cache['llm'])} finnhub={list(cache['finnhub'])} -> {_fixture_file(ticker).name}")


class _StubAdapter(DataAdapter):
    def __init__(self, raw): self._raw = raw
    def fetch(self, ticker, use_cache=True): return dict(self._raw)


class _StubFinnhub:
    def __init__(self, table): self._t = table
    def get_peer_multiples(self, ticker): return self._t.get(ticker)


class _StubCrypto:
    """replay 时屏蔽 NAV 的网络源(5 案例均非国库股 → holdings None → 不出 NAV，零 rubric 影响)。"""
    def holdings(self, ticker): return None
    def coin_price(self, coin): return None


class _StubFred:
    """replay 时回放录制的 FRED 三指标，让 macro prompt(含指标)确定性复现。缺则数据不足。"""
    def __init__(self, table): self._t = table or {}
    def inflation(self): return self._t.get("inflation", {"value": None, "reason": "replay 无 fred 录制"})
    def unemployment(self): return self._t.get("unemployment", {"value": None, "reason": "replay 无 fred 录制"})
    def yield_curve(self): return self._t.get("yield_curve", {"value": None, "reason": "replay 无 fred 录制"})


class _StubEdgarXBRL:
    """replay 时屏蔽 NAV 的 EDGAR 持仓源(5 案例均非加密披露人 → 不出 NAV，零 rubric 影响)。"""
    def crypto_units(self, ticker): return {"count": None, "is_crypto_filer": False, "reason": "replay stub"}


class _StubEdgarIXBRL:
    """replay 时屏蔽 step-2 原始 iXBRL 多币源(不下 1.5MB、离线确定性)。"""
    def crypto_units_by_coin(self, ticker): return {"coins": None, "reason": "replay stub"}


class _StubConsensus:
    """replay 时屏蔽市场共识信号源(Finnhub/yfinance) → 数据不足、离线确定性、零 rubric 影响。"""
    def analyst_trends(self, ticker): return None
    def short_interest(self, ticker): return None


# ───────────────────────── 跑单案例 ─────────────────────────
def run_case(ticker: str, live: bool = False) -> ResearchState:
    llm.set_cost_ceiling(None); llm.reset_usage()
    if live:
        app = build_graph()
        final = app.invoke(ResearchState(ticker=ticker), config={"recursion_limit": RECURSION_LIMIT})
        return ResearchState.model_validate(final) if isinstance(final, dict) else final

    # replay：重放合成 portfolio fixture
    fx = json.loads(_fixture_file(ticker).read_text())
    orig_llm, orig_adapter, orig_fh = llm.call_structured, stages._DEFAULT_ADAPTER, stages._FINNHUB
    orig_crypto, orig_fred, orig_edgar = stages._CRYPTO, stages._FRED, stages._EDGAR_XBRL
    orig_edgar_ix, orig_consensus = stages._EDGAR_IXBRL, stages._CONSENSUS
    def replay_llm(model, system, user, schema, tool_name="emit", max_tokens=2000):
        if fx.get("fixture_kind") != "synthetic-portfolio-example":
            raise RuntimeError("Portfolio replay requires explicitly synthetic fixtures")
        fields = sorted(schema.get("properties", {}))
        for sample in fx["schema_responses"]:
            if sample["fields"] == fields:
                return json.loads(json.dumps(sample["response"]))
        raise RuntimeError(f"No synthetic response for schema fields: {fields}")
    llm.call_structured = replay_llm
    stages._DEFAULT_ADAPTER = _StubAdapter(fx["raw_data"])
    stages._FINNHUB = _StubFinnhub(fx["finnhub"])
    stages._CRYPTO = _StubCrypto()           # NAV 币价源 replay 屏蔽(离线/确定性)
    stages._FRED = _StubFred(fx.get("fred", {}))   # FRED 三指标回放(离线/确定性)
    stages._EDGAR_XBRL = _StubEdgarXBRL()    # NAV 持仓源(EDGAR 单币) replay 屏蔽(离线/确定性)
    stages._EDGAR_IXBRL = _StubEdgarIXBRL()  # NAV step-2 多币源 replay 屏蔽(离线/确定性)
    stages._CONSENSUS = _StubConsensus()     # 市场共识信号源 replay 屏蔽(离线/确定性)
    try:
        app = build_graph()
        final = app.invoke(ResearchState(ticker=ticker), config={"recursion_limit": RECURSION_LIMIT})
        return ResearchState.model_validate(final) if isinstance(final, dict) else final
    finally:
        llm.call_structured, stages._DEFAULT_ADAPTER, stages._FINNHUB = orig_llm, orig_adapter, orig_fh
        stages._CRYPTO = orig_crypto
        stages._FRED = orig_fred
        stages._EDGAR_XBRL = orig_edgar
        stages._EDGAR_IXBRL = orig_edgar_ix
        stages._CONSENSUS = orig_consensus


# ───────────────────────── 评测(全案例打分) ─────────────────────────
def evaluate(live: bool = False) -> dict:
    total_pass = total = 0
    report = {}
    for ticker, rubric in CASES.items():
        try:
            state = run_case(ticker, live=live)
            checks = rubric(state)
        except Exception as e:  # noqa: BLE001
            checks = [("案例执行失败", False), (f"err:{type(e).__name__}", False)]
        passed = sum(1 for _, ok in checks if ok)
        report[ticker] = {"checks": checks, "passed": passed, "total": len(checks)}
        total_pass += passed; total += len(checks)
    report["_overall"] = {"passed": total_pass, "total": total,
                          "score": round(total_pass / total, 3) if total else 0.0}
    return report


def print_report(report: dict, mode: str):
    print(f"\n========== 合成流程检查（{mode} 模式）==========")
    for ticker, r in report.items():
        if ticker == "_overall":
            continue
        flag = "✅" if r["passed"] == r["total"] else "❌"
        print(f"{flag} {ticker}: {r['passed']}/{r['total']}")
        for name, ok in r["checks"]:
            print(f"     {'✓' if ok else '✗ ←退步'} {name}")
    o = report["_overall"]
    print(f"\n总分: {o['passed']}/{o['total']} = {o['score']*100:.1f}%")


if __name__ == "__main__":
    if "--record" in sys.argv:
        for tk in CASES:
            print(f"recording {tk} (live) ...")
            record(tk)
    else:
        mode = "live" if "--live" in sys.argv else "replay"
        print_report(evaluate(live=(mode == "live")), mode)
