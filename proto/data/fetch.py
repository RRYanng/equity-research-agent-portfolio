"""
数据层入口（兼容垫片）。

逻辑已搬进 `adapter.YFinanceAdapter`（Phase 1 step1，节点经 DataAdapter 取数）。
这里只保留 `fetch_ticker` / `risk_free_rate` 旧入口，委托给 adapter，
让任何历史 import 继续可用、行为不变。
"""
from __future__ import annotations

from .adapter import YFinanceAdapter

_adapter = YFinanceAdapter()


def fetch_ticker(ticker: str, use_cache: bool = True) -> dict:
    return _adapter.fetch(ticker, use_cache=use_cache)


def risk_free_rate() -> dict:
    return _adapter.risk_free_rate()
