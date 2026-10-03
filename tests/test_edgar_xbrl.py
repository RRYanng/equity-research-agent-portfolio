"""
EdgarCryptoAdapter 单测（NAV v2 step-1）—— 注入假 HTTP + 假 cik_lookup，离线跑，不碰真网络。

守死（决定 v2 诚实还是重演 v1 bug）：
  · 严格单币：companyconcept 的 CryptoAssetNumberOfUnits 恰好 1 个可识别币名 uom → 取一手单位数。
  · **多币 / uom=Integer / 未识别 → count=None（绝不返回数字）**，reason 推 step-2。
    ← companyconcept 剥掉维度后的聚合数无法按币归属，硬算 = 重演 v1 多币张冠李戴 bug。
  · 404（无该 tag）→ 非加密披露人（is_crypto_filer=False）；网络失败 → None 不崩。
  · as_of 用申报期末（fact end），不冒充实时。
"""
import sys
from numbers import Number
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.data.edgar_xbrl import EdgarCryptoAdapter


def _adapter(payload=None, exc=None, cik=1050446):
    def http(url):
        if exc is not None:
            raise exc
        return payload
    return EdgarCryptoAdapter(cik_lookup=lambda t: cik, http_json=http, cache=False)


# ① 单币（uom=Bitcoin，MSTR 式）→ 取最新期末的一手单位数
def test_single_coin_bitcoin_returns_units():
    payload = {"units": {"Bitcoin": [
        {"end": "2025-12-31", "val": 500000, "form": "10-K", "accn": "a"},
        {"end": "2026-03-31", "val": 762099, "form": "10-Q", "accn": "b"},
    ]}}
    r = _adapter(payload).crypto_units("MSTR")
    assert r["coin"] == "bitcoin"
    assert r["count"] == 762099
    assert r["as_of"] == "2026-03-31"          # 申报期末，非实时
    assert "EDGAR" in r["source"]
    assert r["is_crypto_filer"] is True


# ② uom=Integer only（BMNR 式，多币聚合）→ 绝不返回数字，推 step-2
def test_integer_uom_multicoin_returns_none_never_number():
    payload = {"units": {"Integer": [
        {"end": "2026-02-28", "val": 4473654, "form": "10-Q", "accn": "c"},
    ]}}
    r = _adapter(payload).crypto_units("BMNR")
    assert r["count"] is None
    assert not isinstance(r["count"], Number)   # ← 红线：多币绝不返回数字
    assert r["is_crypto_filer"] is True
    assert "step-2" in r["reason"]


# ③ HTTP 404（无该 tag，AAPL 式）→ 非加密披露人
def test_http_404_not_a_crypto_filer():
    exc = HTTPError("http://x", 404, "Not Found", {}, None)
    r = _adapter(exc=exc).crypto_units("AAPL")
    assert r["count"] is None
    assert r["is_crypto_filer"] is False


# ④ 网络/解析异常 → None，不崩
def test_http_failure_returns_none_no_crash():
    r = _adapter(exc=ConnectionError("network down")).crypto_units("MSTR")
    assert r["count"] is None
    assert not isinstance(r["count"], Number)


# ⑤ 多个干净币名 uom（Bitcoin+Ethereum，无 Integer）→ 严格单币 only 仍判数据不足、推 step-2
def test_multiple_clean_coin_uoms_still_none_strict_single_coin():
    payload = {"units": {
        "Bitcoin": [{"end": "2026-03-31", "val": 198, "form": "10-Q", "accn": "d"}],
        "Ethereum": [{"end": "2026-03-31", "val": 5700000, "form": "10-Q", "accn": "e"}],
    }}
    r = _adapter(payload).crypto_units("XYZ")
    assert r["count"] is None
    assert not isinstance(r["count"], Number)   # 绝不擅自求和（可能漏了用 Integer 报的第三个币）
    assert "step-2" in r["reason"]
