"""
EDGAR 原始 inline-XBRL 维度解析（NAV v2 step-2，窄版）—— 处理多币持有者。

step-1 的 companyconcept JSON API 剥掉 CryptoAssetAxis 维度，多币只剩无法归属的聚合数。
这里下**主 inline-XBRL 文档**（form10-q.htm，~1.5MB）、按 `srt:CryptoAssetAxis` 逐币成员取
`CryptoAssetNumberOfUnits`，用标准 `<ix:nonFraction>`（软件无关，不依赖 filer 的 xdx id 约定）。

窄版口径（守死，防重演 v1 张冠李戴 bug）：
  · 成员 local name **精确** ∈ {BitcoinMember, EthereumMember} 才映射；聚合(无成员)忽略。
  · 通用成员(DigitalAssetsOneMember 等)/任何认不出的 axis 成员 → **整个 ticker 判数据不足**，
    绝不部分求和(可能漏币)、绝不解析 label linkbase 去猜。
  · 口径 = 一手单位数(申报期末) × 实时币价(币价由 crypto.py 提供)。

懒加载：只有 _build_nav 在 step-1 判到多币时才调这里（下 1.5MB）。任何失败 → coins=None、不崩。
filing 不可变 → 主文档 + 解析结果按 accession 永久缓存；submissions 按天缓存。
"""
from __future__ import annotations

import re
import json
import datetime as dt
import urllib.request
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)

_UA = "ai-equity-research-prototype contact@example.com"
_SUBS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCH = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{doc}"
# 窄版冻结表：成员 local name → 内部币种 id（与 crypto.py._COINS 对齐）。新币要加需单独一行+真实案例测试。
_COIN_MEMBER = {"BitcoinMember": "bitcoin", "EthereumMember": "ethereum"}
_TAG = "CryptoAssetNumberOfUnits"


def _today() -> str:
    return dt.date.today().isoformat()


def _http_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:   # 1.5MB 文档，超时放宽
        return r.read().decode("utf-8", "replace")


def _na(reason: str) -> dict:
    return {"coins": None, "reason": reason}


def _local_name(qname: str) -> str:
    """'BMNR:BitcoinMember' → 'BitcoinMember'（去 filer 自定义命名空间前缀）。"""
    return qname.split(":", 1)[1] if ":" in qname else qname


def _clean_value(inner: str, attrs: str):
    """ix:nonFraction 内文 → 数值：去标签/逗号，按 scale 缩放、sign 取负。失败 → None。"""
    text = re.sub(r"<[^>]+>", "", inner).replace(",", "").strip()
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    sc = re.search(r'\bscale="(-?\d+)"', attrs)
    if sc:
        v *= 10 ** int(sc.group(1))
    if re.search(r'\bsign="-"', attrs):
        v = -v
    return int(v) if v == int(v) else v


class EdgarDimCryptoAdapter:
    """原始 iXBRL 逐币持仓单位数（严格窄版）。失败/多币不可归属 → coins=None，不崩、不猜。"""

    def __init__(self, cik_lookup, fetch=_http_text, cache: bool = True):
        self._cik_lookup = cik_lookup
        self._fetch = fetch
        self._cache = cache

    # --- 找最新一期 10-Q/10-K（inline XBRL）→ (accession, primaryDocument, reportDate) ---
    def _latest_filing(self, cik: int):
        subs_file = CACHE_DIR / f"edgar_subs_{int(cik):010d}_{_today()}.json"
        subs = None
        if self._cache and subs_file.exists():
            try:
                subs = json.loads(subs_file.read_text())
            except Exception:  # noqa: BLE001
                subs = None
        if subs is None:
            subs = json.loads(self._fetch(_SUBS.format(cik=int(cik))))
            if self._cache:
                subs_file.write_text(json.dumps(subs))
        rec = (subs.get("filings", {}) or {}).get("recent", {}) or {}
        forms = rec.get("form", [])
        for i, form in enumerate(forms):
            if form in ("10-Q", "10-K") and (rec.get("isInlineXBRL", [])[i:i + 1] or [0])[0]:
                return (rec["accessionNumber"][i], rec["primaryDocument"][i], rec["reportDate"][i])
        return None

    def _primary_doc(self, cik: int, accn: str, doc: str) -> str:
        cache_file = CACHE_DIR / f"edgar_ixbrl_{accn.replace('-', '')}.htm"   # filing 不可变 → 永久缓存
        if self._cache and cache_file.exists():
            return cache_file.read_text()
        htm = self._fetch(_ARCH.format(cik=int(cik), accn=accn.replace("-", ""), doc=doc))
        if self._cache:
            cache_file.write_text(htm)
        return htm

    def crypto_units_by_coin(self, ticker: str) -> dict:
        cik = self._cik_lookup(ticker)
        if not cik:
            return _na("无 CIK（非 SEC 申报人）")
        try:
            filing = self._latest_filing(cik)
            if filing is None:
                return _na("无最新 10-Q/10-K（inline XBRL）")
            accn, doc, report_date = filing
            htm = self._primary_doc(cik, accn, doc)
        except Exception:  # noqa: BLE001 — 网络/解析失败 → 数据不足，不崩、不 fallback
            return _na("EDGAR iXBRL 取数失败（网络/解析）")

        # context id → CryptoAssetAxis 成员 QName（无该维度则不入表）+ instant
        ctx_member, ctx_instant = {}, {}
        for m in re.finditer(r'<(?:\w+:)?context id="([^"]+)"[^>]*>(.*?)</(?:\w+:)?context>', htm, re.S):
            cid, body = m.group(1), m.group(2)
            inst = re.search(r'<(?:\w+:)?instant>([^<]+)</', body)
            ctx_instant[cid] = inst.group(1).strip() if inst else None
            em = re.search(r'dimension="[^"]*CryptoAssetAxis"[^>]*>([^<]+)<', body)
            if em:
                ctx_member[cid] = em.group(1).strip()

        # 逐个 CryptoAssetNumberOfUnits fact（只看本期 report_date）
        coins: dict[str, float] = {}
        for fm in re.finditer(r'<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>', htm, re.S | re.I):
            attrs, inner = fm.group(1), fm.group(2)
            if _TAG not in attrs:
                continue
            cref_m = re.search(r'contextRef="([^"]+)"', attrs)
            if not cref_m:
                continue
            cref = cref_m.group(1)
            if ctx_instant.get(cref) != report_date:      # 只取本期期末，避开比较期
                continue
            member = ctx_member.get(cref)                  # None = 聚合(无 axis 成员)
            if member is None:
                continue                                   # 聚合忽略：不计、不拒
            local = _local_name(member)
            if local not in _COIN_MEMBER:
                return _na(f"含无法归属的 CryptoAssetAxis 成员({member})：绝不猜是哪个币，整体判数据不足(窄版)")
            val = _clean_value(inner, attrs)
            if val is None:
                return _na(f"{local} 单位数解析失败")
            coin = _COIN_MEMBER[local]
            coins[coin] = coins.get(coin, 0) + val

        if not coins:
            return _na("本期无可归属币种的 CryptoAssetNumberOfUnits（仅聚合/无数据）")
        return {
            "coins": [{"coin": c, "count": n} for c, n in coins.items()],
            "as_of": report_date,
            "source": f"SEC EDGAR 10-Q/10-K iXBRL (form doc, period {report_date})",
            "accn": accn,
        }
