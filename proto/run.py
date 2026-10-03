"""
正式入口：构建 StateGraph → invoke → 渲染 Memo + 纵向记忆 diff。

护栏(Phase 9)：
 - 全链路硬成本上限(USD)：run 开头 set_cost_ceiling + reset_usage；触及上限 → CostCeilingExceeded
   被捕获 → 从 checkpointer 取已完成部分 → 产出"⚠️ 触及成本上限"残缺 memo；残缺 run 不写 watchlist 基线。
 - recursion_limit + 唯一 thread_id(每次全新 run，不 resume 陈旧 checkpoint)。
 - 每份 memo 记录本次实际花费。
"""
from __future__ import annotations

import os
import sys
import datetime as dt
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from .state import ResearchState
from .graph import build_graph, RECURSION_LIMIT
from .memo import render_memo
from . import llm, watchlist

CHECKPOINT_DB = Path(__file__).resolve().parents[1] / "data_cache" / "research_checkpoint.sqlite"
# 默认单次 run 硬成本上限(USD)，可配置(env RESEARCH_COST_CEILING_USD 或 run(ticker, ceiling=...))
DEFAULT_COST_CEILING = float(os.environ.get("RESEARCH_COST_CEILING_USD", "3.0"))


def _cost_footer(ceiling: float, incomplete: bool) -> str:
    u = llm.usage_summary()
    tag = "（⚠️ 触及上限，残缺）" if incomplete else ""
    return (f"\n\n---\n*本次实际花费: **${u['est_cost_usd']:.3f}** / 上限 ${ceiling:.2f} · "
            f"LLM 调用 {u['calls']} 次{tag}*")


def _partial_memo(ticker: str, state: ResearchState, notice: str, ceiling: float) -> str:
    """触及成本上限时的残缺 memo：只列已完成阶段 + 明确停因，绝不假装完整。"""
    done = lambda v: "✓ 已完成" if v is not None else "— 未运行"
    L = [
        f"# Investment Memo — {ticker}  ⚠️ INCOMPLETE",
        f"\n> ⚠️ **{notice}**",
        f"\n> 本次为**残缺结论**，已停在中途，**不写入 watchlist 历史**（不污染'相比上次'基线）。",
        f"\n## 已完成阶段",
        f"- 数据/分级: {done(state.tier)}",
        f"- 宏观: {done(state.macro_view)} · 行业: {done(state.industry_view)}",
        f"- 公司: {done(state.company_view)} · 财务: {done(state.financial_view)}",
        f"- 估值: {done(state.valuation_view)} · 风险: {done(state.risk_view)}",
        f"- 委员会/Memo: {done(state.memo)}",
        _cost_footer(ceiling, incomplete=True),
    ]
    return "\n".join(L)


def run(ticker: str, out_dir: str = "output", ceiling: float | None = None) -> ResearchState:
    ceiling = DEFAULT_COST_CEILING if ceiling is None else ceiling
    print(f"[run] researching {ticker} via StateGraph ... (cost ceiling ${ceiling:.2f})")
    CHECKPOINT_DB.parent.mkdir(exist_ok=True)

    # 护栏：清零成本累计 + 设硬上限
    llm.reset_usage()
    llm.set_cost_ceiling(ceiling)

    prev = watchlist.get_last(ticker)        # 上次【完整】结论(残缺 run 已被排除)
    incomplete, notice = False, ""

    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        app = build_graph(checkpointer=saver)
        thread_id = f"{ticker}-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
        cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
        try:
            final = app.invoke(ResearchState(ticker=ticker), config=cfg)
            state = ResearchState.model_validate(final) if isinstance(final, dict) else final
        except llm.CostCeilingExceeded as e:
            incomplete, notice = True, str(e)
            snap = app.get_state(cfg)         # 从 checkpointer 取已完成部分
            state = (ResearchState.model_validate(snap.values)
                     if snap and snap.values else ResearchState(ticker=ticker))
        persisted = app.get_state(cfg)
        ckpt_ok = persisted is not None and persisted.values is not None

    # 渲染落盘：完整 → 正常 memo + 成本页脚；残缺 → 残缺 memo
    Path(out_dir).mkdir(exist_ok=True)
    if incomplete or state.memo is None:
        incomplete = True
        md = _partial_memo(ticker, state, notice or "分析未完成", ceiling)
    else:
        md = render_memo(state) + _cost_footer(ceiling, incomplete=False)
    fname = Path(out_dir) / f"{ticker}_memo_{dt.date.today().isoformat()}.md"
    fname.write_text(md)

    # 纵向记忆：残缺 run 不写基线(防污染)；完整 run 先 diff 再记录
    if incomplete:
        diff = "纵向记忆：本次残缺(触及成本上限)，不写入 watchlist 历史基线。"
    else:
        diff = watchlist.diff_report(prev, state)
        watchlist.record(state, incomplete=False)

    u = llm.usage_summary()
    rating = state.memo.rating if state.memo else "INCOMPLETE"
    conf = state.memo.confidence if state.memo else "—"
    print(f"[run] tier={state.tier.value if state.tier else 'n/a'} rating={rating}({conf}) "
          f"incomplete={incomplete}")
    print(f"[run] memo -> {fname}")
    print(f"[checkpoint] SqliteSaver persisted={ckpt_ok} (thread_id={thread_id})")
    print(f"[memory] {diff}")
    print(f"[cost] calls={u['calls']} est=${u['est_cost_usd']:.3f} / ceiling ${ceiling:.2f}"
          + ("  ⚠️ STOPPED at ceiling" if incomplete and notice else ""))
    return state


def run_stream(ticker: str, ceiling: float | None = None):
    """
    流式版(Phase 10)：用 LangGraph 原生 app.stream 每个节点跑完就 yield 一个进度事件，
    末尾 yield 结构化最终 state；触及成本上限 yield stopped。复用 watchlist 记录 + 残缺隔离。

    yield 的是 python dict(含 ResearchState 对象)——web 层负责序列化，proto 不依赖 web。
    事件类型：
      {"type":"node", "node":str, "status":"done"/"degraded", "cost":float}
      {"type":"memo", "state":ResearchState, "diff":str, "cost":float, "ceiling":float}
      {"type":"stopped", "notice":str, "state":ResearchState, "cost":float, "ceiling":float}
    """
    ceiling = DEFAULT_COST_CEILING if ceiling is None else ceiling
    CHECKPOINT_DB.parent.mkdir(exist_ok=True)
    llm.reset_usage()
    llm.set_cost_ceiling(ceiling)
    prev = watchlist.get_last(ticker)
    incomplete, notice = False, ""

    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        app = build_graph(checkpointer=saver)
        thread_id = f"{ticker}-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
        cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
        try:
            for chunk in app.stream(ResearchState(ticker=ticker), config=cfg, stream_mode="updates"):
                for node_name, update in (chunk or {}).items():
                    degraded = bool(isinstance(update, dict) and update.get("node_failures"))
                    yield {"type": "node", "node": node_name,
                           "status": "degraded" if degraded else "done",
                           "cost": round(llm.usage_summary()["est_cost_usd"], 4)}
        except llm.CostCeilingExceeded as e:
            incomplete, notice = True, str(e)
        snap = app.get_state(cfg)
        state = (ResearchState.model_validate(snap.values)
                 if snap and snap.values else ResearchState(ticker=ticker))

    cost = round(llm.usage_summary()["est_cost_usd"], 4)
    if incomplete or state.memo is None:
        yield {"type": "stopped", "notice": notice or "分析未完成（无最终结论）",
               "state": state, "cost": cost, "ceiling": ceiling}
    else:
        diff = watchlist.diff_report(prev, state)
        watchlist.record(state, incomplete=False)
        yield {"type": "memo", "state": state, "diff": diff, "cost": cost, "ceiling": ceiling}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "AAPL")
