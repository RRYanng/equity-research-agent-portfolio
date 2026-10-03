"""
FRED 宏观数据源（Phase 3）—— CPI / 失业率 / 2Y·10Y 国债收益率。

参照 crypto.py：独立数据源模块、按天缓存规避限频（FRED 免费 120 req/min，
我们一天最多拉 4 个 series）、任何失败返回 {"value": None, "reason"}（绝不崩链、绝不编）。
网络 I/O 在这里；确定性计算（CPI YoY / 曲线价差）委托 proto/macro_indicators.py 的纯函数。

指标数字全部来自 FRED 真实 observation，LLM 永不参与生成——只在 macro_stage 解读。
key 从 FRED_API_KEY 读；缺 key → 全部数据不足（像 Finnhub 那样优雅降级）。
"""
from __future__ import annotations

import json
import datetime as dt
import urllib.parse
import urllib.request
from pathlib import Path

from .. import macro_indicators as mi

CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)

_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _today() -> str:
    return dt.date.today().isoformat()


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "equity-research/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _na(reason: str) -> dict:
    return {"value": None, "reason": reason}


class FredAdapter:
    """FRED 三指标。失败一律数据不足，不抛、不编。http_json/cache 可注入便于离线测试。"""

    def __init__(self, api_key: str | None = None, http_json=_http_json, cache: bool = True):
        self._key = api_key
        self._http = http_json
        self._cache = cache

    # ---- 取某 series 最新 N 条 observation（按天缓存）。无 key/失败 → None ----
    def _observations(self, series_id: str, limit: int):
        if not self._key:
            return None
        cache_file = CACHE_DIR / f"fred_{series_id}_{_today()}.json"
        if self._cache and cache_file.exists():
            try:
                return json.loads(cache_file.read_text())
            except Exception:  # noqa: BLE001 — 缓存坏就重拉
                pass
        params = urllib.parse.urlencode({
            "series_id": series_id, "api_key": self._key, "file_type": "json",
            "sort_order": "desc", "limit": limit,
        })
        try:
            data = self._http(f"{_BASE}?{params}")
            obs = data.get("observations")
            if self._cache and obs is not None:
                cache_file.write_text(json.dumps(obs, ensure_ascii=False))
            return obs
        except Exception:  # noqa: BLE001 — 网络/解析失败 → None，上层标数据不足
            return None

    def _latest_yield(self, series_id: str):
        """某 series 最新有效收益率 → {"value": 小数, "as_of": 交易日} 或 None。"""
        obs = self._observations(series_id, 5)          # 多取几天，跳过节假日 "."
        if obs is None:
            return None
        latest = mi.latest_observation(obs)
        if latest is None:
            return None
        date, pct = latest
        return {"value": round(pct / 100, 4), "as_of": date}

    # ---- 对外三指标 ----
    def inflation(self) -> dict:
        """CPI 同比通胀（自算 YoY）。"""
        obs = self._observations("CPIAUCSL", 14)         # 覆盖最新月 + 去年同月
        if obs is None:
            return _na("FRED 未返回 CPI（无 key 或网络失败）")
        return mi.yoy_inflation(obs)

    def unemployment(self) -> dict:
        """失业率最新值（百分比 → 小数）。"""
        obs = self._observations("UNRATE", 2)
        if obs is None:
            return _na("FRED 未返回失业率（无 key 或网络失败）")
        latest = mi.latest_observation(obs)
        if latest is None:
            return _na("无有效失业率观测")
        date, pct = latest
        return {"value": round(pct / 100, 4), "as_of": date[:7], "source": "FRED UNRATE"}

    def yield_curve(self) -> dict:
        """2s10s 价差 + 倒挂判定（自算）。缺任一腿 → 数据不足。"""
        return mi.curve_state(self._latest_yield("DGS2"), self._latest_yield("DGS10"))
