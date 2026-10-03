"""
EdgarDimCryptoAdapter 单测（NAV v2 step-2 窄版）—— 原始 inline-XBRL 维度解析，注假 fetch 离线跑。

fixture 忠实照真实 BMNR 10-Q(period 2026-02-28) 的 iXBRL 结构：
  <ix:nonFraction name="us-gaap:CryptoAssetNumberOfUnits" contextRef="…" unitRef="Integer">195</ix:nonFraction>
  <xbrli:context id="…"><xbrli:segment><xbrldi:explicitMember dimension="srt:CryptoAssetAxis">BMNR:BitcoinMember</…></…>

守死（窄版口径）：
  · 成员 local name **精确** ∈ {BitcoinMember, EthereumMember} 才映射币种、求和。
  · 聚合 fact(无 axis 成员) → 忽略(不计不拒)。
  · 通用成员(DigitalAssetsOneMember 等)/任何认不出的 axis 成员 → **整个 ticker 判数据不足**，
    绝不部分求和(可能漏币)、绝不解析 label 猜。
  · 值清洗：去逗号、按 scale 缩放。
"""
import sys
import json
from numbers import Number
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.data.edgar_ixbrl import EdgarDimCryptoAdapter

_SUBS = json.dumps({"filings": {"recent": {
    "form": ["10-Q"], "filingDate": ["2026-04-14"], "reportDate": ["2026-02-28"],
    "accessionNumber": ["0001493152-26-016560"], "primaryDocument": ["form10-q.htm"],
    "isInlineXBRL": [1],
}}})


def _ctx(cid, member=None, instant="2026-02-28"):
    seg = (f'<xbrli:segment><xbrldi:explicitMember dimension="srt:CryptoAssetAxis">'
           f'{member}</xbrldi:explicitMember></xbrli:segment>') if member else ""
    return (f'<xbrli:context id="{cid}"><xbrli:entity>'
            f'<xbrli:identifier scheme="http://www.sec.gov/CIK">0001829311</xbrli:identifier>{seg}'
            f'</xbrli:entity><xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period></xbrli:context>')


def _fact(cref, val, scale=None):
    sc = f' scale="{scale}"' if scale is not None else ""
    return (f'<ix:nonFraction name="us-gaap:CryptoAssetNumberOfUnits" contextRef="{cref}" '
            f'id="Fx" format="ixt:numdotdecimal" decimals="INF"{sc} unitRef="Integer">{val}</ix:nonFraction>')


def _adapter(htm, exc=None, cik=1829311, subs=_SUBS):
    def fetch(url):
        if "submissions" in url:
            return subs
        if exc is not None:
            raise exc
        return htm
    return EdgarDimCryptoAdapter(cik_lookup=lambda t: cik, fetch=fetch, cache=False)


def _coins_map(r):
    return {c["coin"]: c["count"] for c in (r.get("coins") or [])}


# ① BMNR 式：BTC 195 + ETH 4,473,459 + 聚合 4,473,654 → 拆出两币，聚合忽略
def test_bmnr_two_coins_split():
    htm = (_ctx("c_btc", "BMNR:BitcoinMember") + _ctx("c_eth", "BMNR:EthereumMember") + _ctx("c_agg")
           + _fact("c_btc", "195") + _fact("c_eth", "4,473,459") + _fact("c_agg", "4,473,654"))
    r = _adapter(htm).crypto_units_by_coin("BMNR")
    assert _coins_map(r) == {"bitcoin": 195, "ethereum": 4473459}
    assert r["as_of"] == "2026-02-28"          # 申报期末
    assert "iXBRL" in r["source"] or "EDGAR" in r["source"]


# ② 只有聚合成员(无 axis 成员) → 数据不足，绝不返回数字
def test_aggregate_only_is_data_insufficient():
    htm = _ctx("c_agg") + _fact("c_agg", "4,473,654")
    r = _adapter(htm).crypto_units_by_coin("BMNR")
    assert r["coins"] is None
    assert not isinstance(r.get("coins"), Number)
    assert "reason" in r


# ③ 只有通用成员(DigitalAssetsOneMember) → 数据不足，绝不猜是哪个币
def test_generic_member_only_rejected():
    htm = _ctx("c_g", "BMNR:DigitalAssetsOneMember") + _fact("c_g", "100")
    r = _adapter(htm).crypto_units_by_coin("XYZ")
    assert r["coins"] is None
    assert "reason" in r


# ④ 混合：BitcoinMember + 一个通用成员的 units fact → 整体拒(绝不只取 BTC 漏掉那个)
def test_mixed_recognized_and_generic_rejects_whole():
    htm = (_ctx("c_btc", "BMNR:BitcoinMember") + _ctx("c_g", "BMNR:DigitalAssetsThreeMember")
           + _fact("c_btc", "195") + _fact("c_g", "999"))
    r = _adapter(htm).crypto_units_by_coin("XYZ")
    assert r["coins"] is None                   # 整体拒，不是 {bitcoin:195}
    assert not isinstance(r.get("coins"), Number)


# ⑤ 值清洗：去逗号 + 按 scale 缩放
def test_value_parsing_commas_and_scale():
    htm = (_ctx("c_btc", "BMNR:BitcoinMember") + _ctx("c_eth", "BMNR:EthereumMember")
           + _fact("c_btc", "1,234") + _fact("c_eth", "5", scale="3"))   # 5 × 10^3 = 5000
    r = _adapter(htm).crypto_units_by_coin("XYZ")
    assert _coins_map(r) == {"bitcoin": 1234, "ethereum": 5000}


# ⑥ HTTP 失败 / 无 10-Q → 数据不足，不崩
def test_http_failure_and_no_filing():
    r1 = _adapter("", exc=ConnectionError("network down")).crypto_units_by_coin("BMNR")
    assert r1["coins"] is None and "reason" in r1
    no10q = json.dumps({"filings": {"recent": {
        "form": ["8-K"], "filingDate": ["2026-04-14"], "reportDate": ["2026-02-28"],
        "accessionNumber": ["x"], "primaryDocument": ["x.htm"], "isInlineXBRL": [1]}}})
    r2 = _adapter("<html/>", subs=no10q).crypto_units_by_coin("BMNR")
    assert r2["coins"] is None
