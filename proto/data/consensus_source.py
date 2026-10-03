"""
市场共识信号数据源（Phase 5 · 诚实版）—— 只取硬数据、可溯源。

· analyst_trends：Finnhub `recommendation_trends`（免费档，客户端已在栈里）。
· short_interest：yfinance 短仓字段（sharesShort / sharesShortPriorMonth / shortPercentOfFloat / dateShortInterest）。

只做 I/O（返回 raw），确定性计算在 proto/consensus.py。按天缓存、失败一律 None（不崩、不编、不 fallback）。
DI 可注入 rec_fetch/short_fetch 便于离线测试（照 fred.py/edgar_xbrl.py 风格）。
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _today() -> str:
    return dt.date.today().isoformat()


def _default_rec_fetch(ticker: str):
    import finnhub
    import os
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    return finnhub.Client(api_key=key).recommendation_trends(ticker)


def _default_short_fetch(ticker: str):
    import yfinance as yf
    info = yf.Ticker(ticker).info or {}
    return {k: info.get(k) for k in
            ("sharesShort", "sharesShortPriorMonth", "shortPercentOfFloat", "dateShortInterest")}


class ConsensusAdapter:
    """分析师评级趋势 + 短仓，返回 raw。失败一律 None。可注入 fetch/cache 便于测试。"""

    def __init__(self, finnhub_api_key: str | None = None,
                 rec_fetch=None, short_fetch=None, cache: bool = True):
        self._key = finnhub_api_key
        self._rec = rec_fetch or _default_rec_fetch
        self._short = short_fetch or _default_short_fetch
        self._cache = cache

    def _cached(self, kind: str, ticker: str, fetch):
        cache_file = CACHE_DIR / f"consensus_{kind}_{ticker.upper()}_{_today()}.json"
        if self._cache and cache_file.exists():
            try:
                return json.loads(cache_file.read_text())
            except Exception:  # noqa: BLE001 — 缓存坏就重拉
                pass
        try:
            data = fetch(ticker)
        except Exception:  # noqa: BLE001 — 网络/解析失败 → None，不崩
            return None
        if self._cache and data is not None:
            cache_file.write_text(json.dumps(data, default=str))
        return data

    def analyst_trends(self, ticker: str):
        return self._cached("rec", ticker, self._rec)

    def short_interest(self, ticker: str):
        return self._cached("short", ticker, self._short)
