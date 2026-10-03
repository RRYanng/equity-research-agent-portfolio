"""
FastAPI 后端（Phase 10 step1）：把 LangGraph agent 的流式 run 包成 SSE。

启动：uvicorn web.api.main:app --reload --port 8000   (从项目根目录)
流式：GET /api/analyze/stream?ticker=AAPL[&ceiling=3.0]

护栏延伸到 API 层：每次 analyze 用成本上限(ceiling 参数或默认)，触顶推 stopped 事件。
agent 逻辑全在 proto，这里只做薄 SSE 包装 + 序列化。
"""
from __future__ import annotations

import json

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from proto.run import run_stream
from .serializers import serialize_state
from .watchlist import router as watchlist_router
from . import reports

app = FastAPI(title="Equity Research Terminal")
app.include_router(watchlist_router)

# 开发态：前端 vite dev 在 :5173，放行 localhost。以后上线可让 FastAPI 直接 serve 打包前端。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.get("/api/health")
def health():
    return {"ok": True, "service": "equity-research-terminal"}


@app.get("/api/reports")
def list_reports():
    """历史列表：每条已归档完整报告的摘要(id/ticker/as_of/rating/saved_at)，最近在前。"""
    return {"items": reports.list()}


@app.get("/api/reports/{rid}")
def get_report(rid: int):
    """回看：返回该 id 的完整报告 json(与实时 memo 事件同构，前端复用 <Result/> 渲染)。"""
    payload = reports.get(rid)
    if payload is None:
        raise HTTPException(status_code=404, detail="report not found")
    return payload


@app.get("/api/analyze/stream")
def analyze_stream(ticker: str = Query(..., min_length=1),
                   ceiling: float | None = Query(None, description="本次成本上限 USD，默认走后端配置")):
    """SSE：每个节点完成推 node 事件，末尾推 memo(或 stopped)，再 done。"""
    def gen():
        try:
            for ev in run_stream(ticker.strip().upper(), ceiling=ceiling):
                t = ev["type"]
                if t == "node":
                    yield _sse("node", {"node": ev["node"], "status": ev["status"], "cost": ev["cost"]})
                elif t == "memo":
                    payload = serialize_state(ev["state"], cost=ev["cost"],
                                              ceiling=ev["ceiling"], diff=ev["diff"])
                    reports.save(payload)          # 完整报告归档(刷新不丢/可回看)；stopped 分支不存
                    yield _sse("memo", payload)
                elif t == "stopped":
                    yield _sse("stopped", serialize_state(ev["state"], cost=ev["cost"],
                                                          ceiling=ev["ceiling"], stopped=True,
                                                          notice=ev["notice"]))
            yield _sse("done", {"ok": True})
        except Exception as e:  # noqa: BLE001 — 任何后端异常都以 error 事件告知前端，不让连接吊死
            yield _sse("error", {"message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})
