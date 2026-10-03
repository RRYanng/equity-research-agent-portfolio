"""
DataAdapter 抽象契约 + YFinanceAdapter 实现（Phase 1 step 1）。

核心契约(blueprint Phase 1)：节点只认 DataAdapter 接口，永不直接 import yfinance。
换源/加源只改实现类，不改任何 stage。fetch() 返回的 raw_data dict 形状对下游稳定。

step 1 只做"把现有 fetch.py 逻辑搬进 YFinanceAdapter"，raw_data 逐字段不变；
peer 倍数源(Finnhub/Damodaran)在 step 2-3 作为独立实现接入 get_peer_multiples。
"""
from __future__ import annotations

import json
import datetime as dt
from abc import ABC, abstractmethod
from pathlib import Path

import yfinance as yf

from ..state import DataTier
from .edgar import EdgarTierResolver

CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _today() -> str:
    return dt.date.today().isoformat()


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# ───────────────────────── 抽象契约 ─────────────────────────
class DataAdapter(ABC):
    """节点面向这个接口取数。换数据源 = 换实现类，不动 stage。"""

    @abstractmethod
    def fetch(self, ticker: str, use_cache: bool = True) -> dict:
        """组装标准化 raw_data（下游 stage 只认这个 dict 形状）。"""

    def resolve_tier(self, ticker: str) -> DataTier:
        """数据分级：默认从 fetch 的 tier 字段取（PUBLIC/PRE_IPO）。"""
        return DataTier(self.fetch(ticker).get("tier", "public"))

    def get_peer_multiples(self, ticker: str) -> dict | None:
        """同业倍数 fair band。基础实现无（peer 源在 Phase1 step2-3 接）。"""
        return None


# ───────────────────────── yfinance 实现 ─────────────────────────
class YFinanceAdapter(DataAdapter):
    """价格/财报/beta/行业分类(yfinance) + 无风险利率(^TNX)。逻辑搬自原 fetch.py，输出不变。"""

    @staticmethod
    def _row(df, *candidates):
        """从 yfinance 财报 DataFrame 里按多个候选行名取最新一期的值；取不到返回 None。"""
        if df is None or getattr(df, "empty", True):
            return None
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                if len(series):
                    return float(series.iloc[0])
        return None

    @staticmethod
    def _row_prior(df, *candidates):
        """取上一期(用于边际变化)。取不到返回 None。"""
        if df is None or getattr(df, "empty", True):
            return None
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                if len(series) >= 2:
                    return float(series.iloc[1])
        return None

    @staticmethod
    def _row_at(df, idx, *candidates):
        """取第 idx 期(0=最新)。用于成长趋势需要的第三期(idx=2)。取不到返回 None。"""
        if df is None or getattr(df, "empty", True):
            return None
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                if len(series) > idx:
                    return float(series.iloc[idx])
        return None

    def risk_free_rate(self) -> dict:
        """
        10Y 美债收益率，取自 ^TNX。^TNX 报价是"收益率×10"(如 4.3% -> 43)，
        但 yfinance 有时已返回百分数值；用 >20 启发式归一化，并把原始值留痕。
        """
        try:
            hist = yf.Ticker("^TNX").history(period="5d")
            if hist.empty:
                raise RuntimeError("empty ^TNX history")
            raw = float(hist["Close"].dropna().iloc[-1])
            pct = raw / 10.0 if raw > 20 else raw     # 归一化到"百分数"
            return {
                "rate": pct / 100.0,                  # 小数，如 0.043
                "raw": raw,
                "source": "yfinance ^TNX (CBOE 10Y Treasury Yield)",
                "timestamp": _now_iso(),
                "ok": True,
            }
        except Exception as e:  # noqa: BLE001 — 数据源失败要 fallback，不让链崩
            return {
                "rate": None, "raw": None, "ok": False, "error": str(e),
                "source": "yfinance ^TNX (FAILED)", "timestamp": _now_iso(),
            }

    def fetch(self, ticker: str, use_cache: bool = True) -> dict:
        """拉一个 ticker 的标准化数据包。失败的字段标 None，不编。"""
        cache_file = CACHE_DIR / f"{ticker}_{_today()}.json"
        if use_cache and cache_file.exists():
            return json.loads(cache_file.read_text())

        _row, _row_prior, _row_at = self._row, self._row_prior, self._row_at
        t = yf.Ticker(ticker)
        try:
            info = t.info or {}
        except Exception:  # noqa: BLE001
            info = {}

        # 财报三表(年度)
        try:
            inc, bal, cf = t.income_stmt, t.balance_sheet, t.cashflow
        except Exception:  # noqa: BLE001
            inc = bal = cf = None

        # 当前价：info 优先，回退到最近收盘
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            try:
                h = t.history(period="5d")
                price = float(h["Close"].dropna().iloc[-1]) if not h.empty else None
            except Exception:  # noqa: BLE001
                price = None

        # earnings 日期(催化剂用)
        earnings_dates = []
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    earnings_dates = [str(d) for d in (ed if isinstance(ed, list) else [ed])]
        except Exception:  # noqa: BLE001
            pass

        rf = self.risk_free_rate()

        fundamentals = {
            "revenue": _row(inc, "Total Revenue", "TotalRevenue"),
            "revenue_prior": _row_prior(inc, "Total Revenue", "TotalRevenue"),
            "gross_profit": _row(inc, "Gross Profit", "GrossProfit"),
            "operating_income": _row(inc, "Operating Income", "OperatingIncome"),
            "operating_income_prior": _row_prior(inc, "Operating Income", "OperatingIncome"),
            "net_income": _row(inc, "Net Income", "NetIncome", "Net Income Common Stockholders"),
            "net_income_prior": _row_prior(inc, "Net Income", "NetIncome", "Net Income Common Stockholders"),
            "total_assets": _row(bal, "Total Assets", "TotalAssets"),
            "shareholders_equity": _row(
                bal, "Stockholders Equity", "Total Stockholder Equity",
                "Common Stock Equity", "Total Equity Gross Minority Interest",
            ),
            "total_debt": _row(bal, "Total Debt", "TotalDebt") or info.get("totalDebt"),
            "cash": _row(
                bal, "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments",
            ) or info.get("totalCash"),
            "operating_cash_flow": _row(cf, "Operating Cash Flow", "Total Cash From Operating Activities"),
            "operating_cash_flow_prior": _row_prior(cf, "Operating Cash Flow", "Total Cash From Operating Activities"),
            "capex": _row(cf, "Capital Expenditure", "Capital Expenditures"),
            "free_cash_flow_reported": _row(cf, "Free Cash Flow"),
            # —— 公司质量层新增(增量、向后兼容)：旧缓存无这些键 → 质量指标自动走"数据不足" ——
            "tax_provision": _row(inc, "Tax Provision", "Income Tax Expense"),
            "pretax_income": _row(inc, "Pretax Income", "Pre Tax Income", "Income Before Tax"),
            "ebitda": _row(inc, "EBITDA", "Normalized EBITDA") or info.get("ebitda"),
            "current_debt": _row(
                bal, "Current Debt", "Current Debt And Capital Lease Obligation",
                "Short Term Debt", "Other Current Borrowings",
            ),
            "revenue_prior2": _row_at(inc, 2, "Total Revenue", "TotalRevenue"),
            "net_income_prior2": _row_at(
                inc, 2, "Net Income", "NetIncome", "Net Income Common Stockholders"),
        }

        net_debt = None
        if fundamentals["total_debt"] is not None and fundamentals["cash"] is not None:
            net_debt = fundamentals["total_debt"] - fundamentals["cash"]

        # —— 修正净现金口径：现金+短投 + 长期有价证券 − 总债务 ——
        cash_st = _row(bal, "Cash Cash Equivalents And Short Term Investments") or fundamentals["cash"]
        lt_securities = _row(
            bal, "Investmentin Financial Assets", "Available For Sale Securities",
            "Investments And Advances",
        ) or 0.0
        total_cash_securities = (cash_st or 0.0) + lt_securities
        net_cash = None  # 正=净现金，负=净负债
        if fundamentals["total_debt"] is not None:
            net_cash = total_cash_securities - fundamentals["total_debt"]

        # —— 回购缩股率：普通股本同比下降幅度，clamp 到 [0, 0.1] ——
        sh_now = _row(bal, "Ordinary Shares Number", "Share Issued")
        sh_prior = _row_prior(bal, "Ordinary Shares Number", "Share Issued")
        buyback_shrink = 0.0
        if sh_now and sh_prior and sh_now < sh_prior:
            buyback_shrink = min(0.10, 1.0 - sh_now / sh_prior)

        pkg = {
            "ticker": ticker,
            "as_of": _now_iso(),
            "tier": "public",   # AAPL：能在公开市场查到财报 → PUBLIC
            "price": price,
            "currency": info.get("currency"),
            "beta": info.get("beta"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "long_name": info.get("longName") or info.get("shortName"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "net_debt": net_debt,                       # 旧口径(仅 cash)，保留对照
            "net_cash": net_cash,                        # 修正口径：含有价证券(正=净现金)
            "cash_st_investments": cash_st,
            "lt_marketable_securities": lt_securities,
            "buyback_shrink": buyback_shrink,            # 年化缩股率
            "ordinary_shares_now": sh_now,
            "ordinary_shares_prior": sh_prior,
            "earnings_dates": earnings_dates,
            "fundamentals": fundamentals,
            "risk_free": rf,
            "business_summary": (info.get("longBusinessSummary") or "")[:1500],
            "source": "yfinance",
        }

        try:
            cache_file.write_text(json.dumps(pkg, indent=2, default=str))
        except Exception:  # noqa: BLE001
            pass
        return pkg


# ───────────────────────── tier 组合判级（EDGAR + 数据存在性，可单测纯函数） ─────────────────────────
def _classify_tier(has_edgar, has_fundamentals: bool):
    """
    组合判级，修两个方向的偏见：
      · 只看 EDGAR 会把有全套财报的成熟 ADR(腾讯/罗氏)误降级 PRE_IPO（反方向偏见）。
      · 只看数据存在性会漏掉"私有公司碰巧有零星行情"的情况。
    规则：
      · 有 SEC 申报 → PUBLIC。
      · 无 SEC 申报但关键财报齐(ADR/外国上市) → 仍 PUBLIC，不误降级。
      · 无 SEC 申报且关键财报缺失 → PRE_IPO（真·数据稀疏，降级 + 低置信）。
    has_edgar 可能为 None(名录网络失败)，按 falsy 处理但靠 fundamentals 兜底，不误降级数据齐的标的。
    """
    if has_edgar:
        return DataTier.PUBLIC, "SEC 申报存在 → PUBLIC"
    if has_fundamentals:
        return DataTier.PUBLIC, "无 SEC 申报但关键财报齐(ADR/外国上市) → 仍按 PUBLIC 分析，不误降级"
    return DataTier.PRE_IPO, "无 SEC 申报且关键财报缺失 → PRE_IPO 数据稀疏，降级 + 低置信"


class CompositeAdapter(DataAdapter):
    """
    组合数据源（#1）：fetch 走 yfinance，tier 走 EDGAR+数据存在性，倍数源(Finnhub/Damodaran)
    由分析层经此 adapter 取。换源/加源只改这里的构造，不动 stage。
    """

    def __init__(self, fetch_provider: DataAdapter | None = None, tier_resolver=None):
        self._yf = fetch_provider or YFinanceAdapter()
        self._edgar = tier_resolver or EdgarTierResolver()

    @staticmethod
    def _has_fundamentals(raw: dict) -> bool:
        f = raw.get("fundamentals", {}) or {}
        return f.get("revenue") is not None and f.get("net_income") is not None

    def resolve_tier(self, ticker: str, raw: dict | None = None) -> DataTier:
        if raw is None:
            raw = self._yf.fetch(ticker)
        tier, _ = _classify_tier(self._edgar.has_sec_filings(ticker), self._has_fundamentals(raw))
        return tier

    def fetch(self, ticker: str, use_cache: bool = True) -> dict:
        raw = self._yf.fetch(ticker, use_cache=use_cache)
        tier, reason = _classify_tier(self._edgar.has_sec_filings(ticker), self._has_fundamentals(raw))
        raw["tier"] = tier.value                      # 覆盖 yfinance 的硬编码 "public"
        raw["data_sparse"] = tier == DataTier.PRE_IPO
        raw["tier_reason"] = reason
        return raw
