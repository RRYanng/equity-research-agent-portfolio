"""
LangGraph StateGraph 编排（Phase 0）。

迁移本质：用图的边替换 run.py 的 for 循环，stage body 不动。
第3步已证：串行全 PUBLIC 链与线性版逐字节等价。
第4步加：tier 条件边(PUBLIC/PRE_IPO) + recursion_limit + 可选 checkpointer。

拓扑（串行，macro/industry 暂不并行——为保与线性版等价）：
  START → data ─┬─(PUBLIC)──────────────> macro → industry → company → financial
                └─(PRE_IPO)→ preipo_gate ↗                                      │
                                                                                ▼
        sensitivity ← committee ← risk ← catalyst ← valuation ←────────────────┘
              │
              ▼  END
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from .state import ResearchState, DataTier
from . import stages, guardrails

RECURSION_LIMIT = 25   # 线性 DAG 约 11 步，留余量但堵死失控烧钱(护栏)

# data 之后的分析链（串行）
_ANALYTICAL = [
    "macro", "industry", "company", "financial",
    "valuation", "catalyst", "risk", "committee",
]
_NODES = {
    "macro": stages.macro_stage,
    "industry": stages.industry_stage,
    "company": stages.company_stage,
    "financial": stages.financial_stage,
    "valuation": stages.valuation_stage,
    "catalyst": stages.catalyst_stage,
    "risk": stages.risk_stage,
    "committee": stages.committee_stage,
}


def route_by_tier(state: ResearchState) -> str:
    """条件边(要求#4)：数据分级分流。PUBLIC 走全链；PRE_IPO 先过降级 gate。"""
    return "preipo_gate" if state.tier == DataTier.PRE_IPO else "macro"


def _preipo_gate(state: ResearchState) -> dict:
    """
    PRE_IPO 降级入口：标注低置信，禁止伪造财报(原则5)。
    标记后并入同一分析链——下游 valuation 因无正 FCF 会被 method_router 自动改走倍数法。
    """
    raw = dict(state.raw_data or {})
    raw["tier_degraded"] = True
    raw["low_confidence"] = True
    return {"raw_data": raw}


def _sensitivity_node(state: ResearchState) -> dict:
    """把 valuation_sensitivity(state)->list 包成节点(返回 state 更新)。不改 stages 原函数。"""
    return {"valuation_sensitivity": stages.valuation_sensitivity(state)}


def build_graph(checkpointer=None):
    """构建并编译图。checkpointer 可选(等价验证时不传；正式入口传 SqliteSaver)。
    每个节点套 circuit breaker(Phase9②)：普通异常→降级续跑，放行 CostCeilingExceeded。"""
    g = StateGraph(ResearchState)
    b = guardrails.breaker
    fb = guardrails.FALLBACKS
    g.add_node("data", b("data", stages.data_stage, fb["data"]))
    g.add_node("preipo_gate", _preipo_gate)
    for name in _ANALYTICAL:
        g.add_node(name, b(name, _NODES[name], fb[name]))
    g.add_node("sensitivity", b("sensitivity", _sensitivity_node, fb["sensitivity"]))
    # 市场共识信号(Phase 5)：跑在 committee 之后 → 结构上不可能驱动评级；LLM-free、纯展示。
    g.add_node("consensus", b("consensus", stages.consensus_stage, fb["consensus"]))

    g.add_edge(START, "data")
    # tier 条件边：PUBLIC→macro，PRE_IPO→preipo_gate→macro
    g.add_conditional_edges("data", route_by_tier,
                            {"macro": "macro", "preipo_gate": "preipo_gate"})
    g.add_edge("preipo_gate", "macro")
    # 分析链串行
    for src, dst in zip(_ANALYTICAL, _ANALYTICAL[1:]):
        g.add_edge(src, dst)
    g.add_edge("committee", "sensitivity")
    g.add_edge("sensitivity", "consensus")   # consensus 在 committee/sensitivity 之后，纯展示终节点
    g.add_edge("consensus", END)

    return g.compile(checkpointer=checkpointer)


def run_graph(ticker: str, checkpointer=None) -> ResearchState:
    """跑全链，返回最终 ResearchState。"""
    app = build_graph(checkpointer=checkpointer)
    cfg = {"recursion_limit": RECURSION_LIMIT}
    if checkpointer is not None:
        cfg["configurable"] = {"thread_id": ticker}
    final = app.invoke(ResearchState(ticker=ticker), config=cfg)
    return ResearchState.model_validate(final) if isinstance(final, dict) else final
