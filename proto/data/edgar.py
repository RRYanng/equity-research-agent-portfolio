"""
SEC EDGAR tier resolver（Phase 1 收尾硬化）。

修复缺口：YFinanceAdapter 之前硬编码 tier="public"，PRE_IPO 分支从没被真实触发。
这里用 EDGAR 申报存在性做真判级（blueprint 原话：能查到 SEC 申报 → PUBLIC，查不到 → PRE_IPO）。

数据源：SEC 免费的 company_tickers.json（ticker→CIK 全表）。SEC fair-access 要求带 User-Agent。
缓存到本地（该表更新不频繁）。网络失败时降级：返回 None 让上游保守处理，不瞎判。
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from ..state import DataTier

_CACHE = Path(__file__).resolve().parents[2] / "data_cache" / "sec_company_tickers.json"
_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC 要求声明 User-Agent（应用名 + 联系方式）。研究原型用途。
_UA = "ai-equity-research-prototype contact@example.com"


class EdgarTierResolver:
    def __init__(self, ticker_set: set[str] | None = None,
                 cik_map: dict[str, int] | None = None):
        self._tickers = ticker_set    # 测试可注入；None 时懒加载
        self._cik_by = cik_map        # ticker(大写)→CIK；NAV v2 companyfacts 需要（测试可注入）

    def _get_tickers(self) -> set[str] | None:
        if self._tickers is not None:
            return self._tickers
        # 本地缓存优先
        if _CACHE.exists():
            try:
                data = json.loads(_CACHE.read_text())
                self._tickers = {row["ticker"].upper() for row in data.values()}
                self._cik_by = {row["ticker"].upper(): row["cik_str"] for row in data.values()}
                return self._tickers
            except Exception:  # noqa: BLE001
                pass
        # 下载（带 UA），缓存
        try:
            req = urllib.request.Request(_URL, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            _CACHE.parent.mkdir(exist_ok=True)
            _CACHE.write_bytes(raw)
            data = json.loads(raw)
            self._tickers = {row["ticker"].upper() for row in data.values()}
            self._cik_by = {row["ticker"].upper(): row["cik_str"] for row in data.values()}
            return self._tickers
        except Exception:  # noqa: BLE001 — 网络失败不崩，返回 None 让上游保守处理
            return None

    def cik_for(self, ticker: str) -> int | None:
        """ticker → CIK（companyfacts/companyconcept 需要）。拿不到映射时返回 None，绝不报错。

        判级(resolve_tier/has_sec_filings)逻辑完全不受影响——这里只是把加载 company_tickers.json
        时顺手保留的 CIK 暴露出来。只注入 ticker_set(旧式)时 _cik_by 为 None → 返回 None。
        """
        if self._cik_by is None:
            self._get_tickers()       # 尝试从缓存/网络加载（会顺带填 _cik_by）
        return self._cik_by.get(ticker.upper()) if self._cik_by else None

    def has_sec_filings(self, ticker: str) -> bool | None:
        """该 ticker 是否是 SEC 注册申报人。None = 名录不可用(网络失败)，无法判定。"""
        tickers = self._get_tickers()
        if tickers is None:
            return None
        return ticker.upper() in tickers

    def resolve_tier(self, ticker: str) -> DataTier:
        """
        有 SEC 申报 → PUBLIC；查不到 → PRE_IPO（数据稀疏，走降级、标低置信）。
        名录不可用时保守按 PUBLIC（避免把真上市公司误判 PRE_IPO；data-sparse 由 fundamentals 兜底信号再标）。
        """
        has = self.has_sec_filings(ticker)
        if has is None:
            return DataTier.PUBLIC   # 名录拿不到时保守，不误降级
        return DataTier.PUBLIC if has else DataTier.PRE_IPO
