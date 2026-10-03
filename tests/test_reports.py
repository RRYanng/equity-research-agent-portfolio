"""
报告归档单测（Phase 10 历史记录）：save→get→list 往返 + 残缺隔离（stopped 不入库）。
纯逻辑，零 LLM/零网络。新文件，不触碰冻结的回归套件。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.api import reports


def _payload(ticker="AAPL", rating="Hold", as_of="2026-06-29", stopped=False):
    """模拟 serialize_state 的输出（只保留归档/列表关心的字段 + 一个嵌套块证明整存整取）。"""
    return {
        "ticker": ticker, "as_of": as_of, "stopped": stopped,
        "decision": (None if stopped else {"rating": rating, "confidence": "high"}),
        "valuation": {"method": "dcf", "scenarios": [{"name": "base"}]},  # 嵌套，验证整存
    }


def test_save_then_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DB", tmp_path / "r.sqlite")
    rid = reports.save(_payload())
    assert isinstance(rid, int)
    got = reports.get(rid)
    assert got == _payload()          # 整存整取，嵌套块一字不差


def test_list_returns_summary_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DB", tmp_path / "r.sqlite")
    id1 = reports.save(_payload("AAPL", "Hold"))
    id2 = reports.save(_payload("MSFT", "Buy"))
    items = reports.list()
    assert [i["id"] for i in items] == [id2, id1]      # 最近在前
    head = items[0]
    assert head["ticker"] == "MSFT" and head["rating"] == "Buy"
    assert head["as_of"] == "2026-06-29"
    assert head["saved_at"]                              # 落库时间戳存在
    # 列表只给摘要，不夹带完整 json（完整报告走 get(id)）
    assert "json" not in head and "valuation" not in head


def test_stopped_payload_not_archived(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DB", tmp_path / "r.sqlite")
    rid = reports.save(_payload(stopped=True))
    assert rid is None                  # 残缺 run 自我排除，不入库
    assert reports.list() == []


def test_get_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DB", tmp_path / "r.sqlite")
    assert reports.get(99999) is None
