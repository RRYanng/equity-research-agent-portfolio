"""
报告归档（Phase 10 历史记录）：把 serialize_state 已经算好的完整报告 json 整存，
让"刷新不丢 + 回看历史"成立。刻意旁挂在 web 层、独立于 proto.watchlist——
watchlist 仍只管"相比上次"的标量 diff，这里只管完整报告存档，职责分离、不碰冻结测试。

用 stdlib sqlite3、零新依赖。残缺/停机(stopped 或无 decision)的 run 在 save() 处自我排除，
绝不进历史(防污染，呼应"残缺隔离"原则)——即便调用方接错线也兜得住。
"""
from __future__ import annotations

import json
import sqlite3
import datetime as dt
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data_cache" / "reports.sqlite"


def _conn():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, as_of TEXT, rating TEXT, saved_at TEXT,
            json TEXT
        )
    """)
    return c


def save(payload: dict) -> int | None:
    """
    存一份完整报告(serialize_state 的输出)。返回新 id。
    残缺/停机(stopped=True 或 decision 缺失)→ 不入库、返回 None。
    """
    if payload.get("stopped") or payload.get("decision") is None:
        return None
    ticker = payload.get("ticker")
    as_of = payload.get("as_of")
    rating = (payload.get("decision") or {}).get("rating")
    saved_at = dt.datetime.now().isoformat(timespec="seconds")
    c = _conn()
    cur = c.execute(
        "INSERT INTO reports (ticker, as_of, rating, saved_at, json) VALUES (?,?,?,?,?)",
        (ticker, as_of, rating, saved_at, json.dumps(payload, ensure_ascii=False)),
    )
    c.commit()
    rid = cur.lastrowid
    c.close()
    return rid


def get(rid: int) -> dict | None:
    """取一份完整报告 json。不存在 → None。"""
    c = _conn()
    row = c.execute("SELECT json FROM reports WHERE id=?", (rid,)).fetchone()
    c.close()
    if not row:
        return None
    return json.loads(row[0])


def list() -> list[dict]:
    """历史列表(摘要，不含完整 json)：最近在前。完整报告走 get(id)。"""
    c = _conn()
    rows = c.execute(
        "SELECT id, ticker, as_of, rating, saved_at FROM reports ORDER BY id DESC"
    ).fetchall()
    c.close()
    keys = ["id", "ticker", "as_of", "rating", "saved_at"]
    return [dict(zip(keys, r)) for r in rows]
