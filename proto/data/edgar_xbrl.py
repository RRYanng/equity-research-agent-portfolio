"""
EDGAR XBRL 加密持仓数据源（NAV v2 step-1）—— 从 SEC companyconcept 直取
`CryptoAssetNumberOfUnits`（一手 10-Q/10-K 披露的持有单位数），替换 CoinGecko 的 count 来源。

口径（守死）：NAV 用「XBRL 持有单位数 × 实时币价」——单位数是**申报期末时点值**（as_of=fact end，
如实标，不冒充实时）；币价另由 crypto.py 的 yfinance 提供。**绝不用 CryptoAssetFairValue**
（季末 USD 公允价值）当当前 NAV。

严格单币 only（step-1 死规则）：companyconcept 剥掉 XBRL 维度后，多币持有者的单位数会退化成
一个无法按币归属的聚合数（如 uom=Integer）。硬算它 = 重演 v1 多币张冠李戴/漏算 bug。
故：**恰好 1 个可识别币名 uom（Bitcoin/Ethereum）→ 取；其余一切（Integer/多币/未识别）
→ count=None + reason 推 step-2（原始 XBRL 维度解析）。绝不返回数字。**

任何失败 → count=None，不崩、不 fallback CoinGecko（本步纯 EDGAR）。参照 fred.py 结构（DI 注入
http_json/cache 便于离线测试）。
"""
from __future__ import annotations

import json
import datetime as dt
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)

_UA = "ai-equity-research-prototype contact@example.com"
_TAG = "CryptoAssetNumberOfUnits"
_BASE = "https://data.sec.gov/api/xbrl/companyconcept"
# XBRL 计量单位(uom) → 我们内部币种 id（与 crypto.py._COINS 对齐）
_COIN_UOM = {"Bitcoin": "bitcoin", "Ethereum": "ethereum"}

_NOT_FOUND = object()   # companyconcept 404（该公司从没报这个 tag）的哨兵


def _today() -> str:
    return dt.date.today().isoformat()


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _na(reason: str, is_crypto_filer) -> dict:
    return {"count": None, "reason": reason, "is_crypto_filer": is_crypto_filer}


def _latest_by_end(facts: list) -> dict | None:
    """取 end 最新且 val 为数值的 fact（申报期末口径）。全无效 → None。"""
    valid = [f for f in facts or []
             if isinstance(f.get("val"), (int, float)) and f.get("end")]
    return max(valid, key=lambda f: f["end"]) if valid else None


class EdgarCryptoAdapter:
    """companyconcept 取 CryptoAssetNumberOfUnits。严格单币；失败/多币一律 count=None。"""

    def __init__(self, cik_lookup, http_json=_http_json, cache: bool = True):
        self._cik_lookup = cik_lookup      # ticker → CIK（int）或 None
        self._http = http_json
        self._cache = cache

    def _fetch_concept(self, cik: int):
        """GET companyconcept（按天缓存）。404 → _NOT_FOUND；网络/解析失败 → None。"""
        cache_file = CACHE_DIR / f"edgar_units_{int(cik):010d}_{_today()}.json"
        if self._cache and cache_file.exists():
            try:
                return json.loads(cache_file.read_text())
            except Exception:  # noqa: BLE001 — 缓存坏就重拉
                pass
        url = f"{_BASE}/CIK{int(cik):010d}/us-gaap/{_TAG}.json"
        try:
            data = self._http(url)
        except HTTPError as e:
            return _NOT_FOUND if e.code == 404 else None
        except Exception:  # noqa: BLE001 — 网络/解析失败 → None
            return None
        if self._cache and isinstance(data, dict):
            cache_file.write_text(json.dumps(data, ensure_ascii=False))
        return data

    def crypto_units(self, ticker: str) -> dict:
        """
        → 成功(严格单币): {coin, count, as_of=申报期末, source, accn, is_crypto_filer:True}
        → 失败/多币: {count:None, reason, is_crypto_filer: bool|None}
        """
        cik = self._cik_lookup(ticker)
        if not cik:
            return _na("无 CIK（非 SEC 申报人或名录不可用）", is_crypto_filer=False)

        data = self._fetch_concept(cik)
        if data is _NOT_FOUND:
            return _na("companyconcept 无 CryptoAssetNumberOfUnits（非加密披露人）",
                       is_crypto_filer=False)
        if data is None:
            return _na("EDGAR 取数失败（网络/解析）", is_crypto_filer=None)

        units = (data or {}).get("units", {})
        keys = list(units.keys())
        # 严格单币：恰好 1 个 uom 键 且 是可识别币名
        if len(keys) == 1 and keys[0] in _COIN_UOM:
            latest = _latest_by_end(units[keys[0]])
            if latest is None:
                return _na("该 tag 无有效数值观测", is_crypto_filer=True)
            return {
                "coin": _COIN_UOM[keys[0]], "count": latest["val"],
                "as_of": latest["end"],
                "source": f"SEC EDGAR XBRL {_TAG} ({latest.get('form')} {latest['end']})",
                "accn": latest.get("accn"), "is_crypto_filer": True,
            }
        # 其余：uom=Integer / 多币 / 未识别 → companyconcept 无法按币归属
        return _na(f"单位数无法按币归属(uom={keys})：多币需原始 XBRL 维度解析(step-2)，绝不硬算",
                   is_crypto_filer=True)
