"""
tier 组合判级单测（Phase1 收尾）：EDGAR + 数据存在性。
零网络：注入 EDGAR ticker 集合 + 构造 raw_data fixture。
重点守住：① 真稀疏(无EDGAR+无财报)→PRE_IPO；② ADR(无EDGAR但财报齐)绝不误判 PRE_IPO。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.state import DataTier
from proto.data.adapter import _classify_tier, CompositeAdapter, DataAdapter
from proto.data.edgar import EdgarTierResolver


# ── 纯函数 _classify_tier 六个组合 ──
def test_edgar_filer_is_public():
    assert _classify_tier(True, True)[0] == DataTier.PUBLIC
    assert _classify_tier(True, False)[0] == DataTier.PUBLIC   # AAPL 即使某字段缺仍 PUBLIC


def test_adr_no_edgar_but_has_data_not_downgraded():
    """反方向偏见守门：腾讯/罗氏这类 ADR 无 SEC 申报但财报齐 → 不能误判 PRE_IPO。"""
    tier, reason = _classify_tier(False, True)
    assert tier == DataTier.PUBLIC
    assert "ADR" in reason or "不误降级" in reason


def test_truly_sparse_is_preipo():
    """无 EDGAR 且关键财报缺失（SpaceX/AABB）→ PRE_IPO。"""
    assert _classify_tier(False, False)[0] == DataTier.PRE_IPO


def test_edgar_unavailable_falls_back_to_data_presence():
    # 名录网络失败(None)：有数据→PUBLIC(不误降级)；无数据→PRE_IPO
    assert _classify_tier(None, True)[0] == DataTier.PUBLIC
    assert _classify_tier(None, False)[0] == DataTier.PRE_IPO


# ── CompositeAdapter.fetch 端到端（注入假 fetch + 假 EDGAR，零网络） ──
class _FakeYF(DataAdapter):
    def __init__(self, raw):
        self._raw = raw

    def fetch(self, ticker, use_cache=True):
        return dict(self._raw)


def _composite(raw, edgar_tickers):
    return CompositeAdapter(fetch_provider=_FakeYF(raw),
                            tier_resolver=EdgarTierResolver(ticker_set=edgar_tickers))


def test_composite_aapl_public():
    raw = {"ticker": "AAPL", "tier": "public", "fundamentals": {"revenue": 4e11, "net_income": 1e11}}
    out = _composite(raw, {"AAPL"}).fetch("AAPL")
    assert out["tier"] == "public" and out["data_sparse"] is False


def test_composite_spacex_preipo():
    raw = {"ticker": "SPACEX", "tier": "public", "fundamentals": {"revenue": None, "net_income": None}}
    out = _composite(raw, set()).fetch("SPACEX")      # 不在 EDGAR
    assert out["tier"] == "pre_ipo" and out["data_sparse"] is True
    assert "PRE_IPO" in out["tier_reason"]


def test_composite_adr_stays_public():
    # 腾讯 ADR：不在 EDGAR，但财报齐 → 仍 public（覆盖 yfinance 硬编码的同时不误降级）
    raw = {"ticker": "TCEHY", "tier": "public", "fundamentals": {"revenue": 9e10, "net_income": 2e10}}
    out = _composite(raw, set()).fetch("TCEHY")
    assert out["tier"] == "public" and out["data_sparse"] is False


# ── cik_for（NAV v2 step-1：把 CIK 从 company_tickers.json 捡回来，供 companyfacts）──
def test_cik_for_returns_cik_when_map_available():
    # 注入 ticker→cik 映射；大小写不敏感
    r = EdgarTierResolver(cik_map={"MSTR": 1050446, "AAPL": 320193})
    assert r.cik_for("mstr") == 1050446
    assert r.cik_for("AAPL") == 320193
    assert r.cik_for("NOPE") is None          # 不在映射 → None，不报错


def test_cik_for_none_when_no_map_available():
    # 旧式只注入 ticker_set（无 cik_map）→ cik_for 优雅返回 None，绝不报错
    r = EdgarTierResolver(ticker_set={"AAPL"})
    assert r.cik_for("AAPL") is None
