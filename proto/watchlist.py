"""
纵向记忆 / watchlist（Phase 0 最小版，对应 blueprint Phase 8 雏形）。

用一张轻量 SQLite 表存每次 run 的结论快照；重跑同一标的时对比上次，输出"相比上次"diff。
刻意独立于 LangGraph checkpointer——checkpointer 负责图状态恢复，这里只负责跨 run 的结论追踪，
职责分离更稳(也规避嵌套 Pydantic 序列化风险)。用 stdlib sqlite3，零新依赖。
"""
from __future__ import annotations

import sqlite3
import datetime as dt
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data_cache" / "watchlist.sqlite"


def _conn():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, ts TEXT, rating TEXT, confidence TEXT,
            expected_value REAL, implied_perp REAL,
            dcf_verdict TEXT, mult_verdict TEXT, method TEXT,
            incomplete INTEGER DEFAULT 0
        )
    """)
    # 老库迁移：补 incomplete 列(已存在则忽略)
    try:
        c.execute("ALTER TABLE runs ADD COLUMN incomplete INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    return c


def _snapshot(state) -> dict:
    m, v = state.memo, state.valuation_view
    return {
        "ticker": state.ticker, "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "rating": m.rating, "confidence": m.confidence,
        "expected_value": m.expected_value_per_share,
        "implied_perp": v.implied_perpetual_growth,
        "dcf_verdict": v.dcf_verdict, "mult_verdict": v.mult_verdict,
        "method": m.valuation_method,
    }


def get_last(ticker: str) -> dict | None:
    """
    取该标的最近一次【完整】结论快照作为 diff 基线。
    incomplete=1 的残缺 run(触及成本上限/严重降级)被排除——绝不让半截结论污染历史追踪。
    """
    c = _conn()
    row = c.execute(
        "SELECT rating,confidence,expected_value,implied_perp,dcf_verdict,mult_verdict,method,ts "
        "FROM runs WHERE ticker=? AND incomplete=0 ORDER BY id DESC LIMIT 1", (ticker,),
    ).fetchone()
    c.close()
    if not row:
        return None
    keys = ["rating", "confidence", "expected_value", "implied_perp",
            "dcf_verdict", "mult_verdict", "method", "ts"]
    return dict(zip(keys, row))


def record(state, incomplete: bool = False) -> None:
    """
    把本次 run 的结论快照写入 watchlist。
    incomplete=True(触及成本上限/严重降级)：仍留痕但标记残缺，不作为后续 diff 基线。
    """
    s = _snapshot(state)
    c = _conn()
    c.execute(
        "INSERT INTO runs (ticker,ts,rating,confidence,expected_value,implied_perp,"
        "dcf_verdict,mult_verdict,method,incomplete) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (s["ticker"], s["ts"], s["rating"], s["confidence"], s["expected_value"],
         s["implied_perp"], s["dcf_verdict"], s["mult_verdict"], s["method"], 1 if incomplete else 0),
    )
    c.commit()
    c.close()


def list_all() -> list[dict]:
    """所有追踪标的的【最近一次完整】结论(供 watchlist 列表用)。残缺 run 不计。"""
    c = _conn()
    rows = c.execute(
        "SELECT ticker, rating, confidence, expected_value, ts, method FROM runs r "
        "WHERE incomplete=0 AND id=(SELECT MAX(id) FROM runs WHERE ticker=r.ticker AND incomplete=0) "
        "ORDER BY ticker"
    ).fetchall()
    c.close()
    keys = ["ticker", "rating", "confidence", "expected_value", "ts", "method"]
    return [dict(zip(keys, r)) for r in rows]


def _history(ticker: str, n: int = 2) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT rating,confidence,expected_value,implied_perp,dcf_verdict,mult_verdict,method,ts "
        "FROM runs WHERE ticker=? AND incomplete=0 ORDER BY id DESC LIMIT ?", (ticker, n),
    ).fetchall()
    c.close()
    keys = ["rating", "confidence", "expected_value", "implied_perp",
            "dcf_verdict", "mult_verdict", "method", "ts"]
    return [dict(zip(keys, r)) for r in rows]


def diff_struct(ticker: str) -> dict:
    """结构化'相比上次'：比该标的最近两次【完整】run。不足两次则 available=False。"""
    h = _history(ticker, 2)
    if len(h) < 2:
        return {"ticker": ticker, "available": False,
                "note": "历史不足两次完整 run，无法 diff"}
    cur, prev = h[0], h[1]
    pe, ce = prev["expected_value"], cur["expected_value"]
    ev_pct = round((ce / pe - 1) * 100, 1) if (pe and ce) else None
    return {
        "ticker": ticker, "available": True, "current": cur, "previous": prev,
        "changes": {
            "rating_changed": (prev["rating"], prev["confidence"]) != (cur["rating"], cur["confidence"]),
            "rating": {"from": f"{prev['rating']}({prev['confidence']})",
                       "to": f"{cur['rating']}({cur['confidence']})"},
            "expected_value": {"from": pe, "to": ce, "pct": ev_pct},
            "implied_perp": {"from": prev["implied_perp"], "to": cur["implied_perp"]},
            "verdict_changed": (prev["dcf_verdict"], prev["mult_verdict"]) != (cur["dcf_verdict"], cur["mult_verdict"]),
        },
    }


def _fmt_perp(x):
    return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "n/a"


def diff_report(prev: dict | None, state) -> str:
    """生成"相比上次"diff。无历史则说明是首次研究。"""
    cur = _snapshot(state)
    if prev is None:
        return "纵向记忆：首次研究该标的，无历史可比。本次结论已存入 watchlist。"

    lines = [f"相比上次（{prev['ts']}）："]
    # 评级 / 置信度
    if prev["rating"] != cur["rating"] or prev["confidence"] != cur["confidence"]:
        lines.append(f"  · 评级: {prev['rating']}({prev['confidence']}) → "
                     f"{cur['rating']}({cur['confidence']})  ⚠️ 变化")
    else:
        lines.append(f"  · 评级: {cur['rating']}({cur['confidence']})  （未变）")
    # 估值锚
    pe, ce = prev["expected_value"], cur["expected_value"]
    if pe and ce:
        d = (ce / pe - 1) * 100 if pe else 0
        tag = "  ⚠️ 变化" if abs(ce - pe) > 0.01 else "  （未变）"
        lines.append(f"  · 估值锚: ${pe} → ${ce}（{d:+.1f}%）{tag}")
    # 隐含永续增长
    pp, cp = prev["implied_perp"], cur["implied_perp"]
    lines.append(f"  · 隐含永续增长: {_fmt_perp(pp)} → {_fmt_perp(cp)}")
    # 镜头判定
    if prev["dcf_verdict"] != cur["dcf_verdict"] or prev["mult_verdict"] != cur["mult_verdict"]:
        lines.append(f"  · 镜头: DCF {prev['dcf_verdict']}→{cur['dcf_verdict']} / "
                     f"倍数 {prev['mult_verdict']}→{cur['mult_verdict']}  ⚠️ 变化")
    return "\n".join(lines)
