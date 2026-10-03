"""watchlist 端点（Phase 10 step2）：复用 proto.watchlist 纵向记忆。"""
from __future__ import annotations

from fastapi import APIRouter

from proto import watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
def list_watchlist():
    """追踪列表：各标的最近一次【完整】结论(评级/置信/估值锚/时间)。"""
    return {"items": watchlist.list_all()}


@router.get("/{ticker}/diff")
def watchlist_diff(ticker: str):
    """结构化'相比上次'：最近两次完整 run 的评级/估值锚/隐含增长/镜头变化。"""
    return watchlist.diff_struct(ticker.strip().upper())
