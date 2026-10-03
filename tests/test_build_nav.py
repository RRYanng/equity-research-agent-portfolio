"""
_build_nav 集成测（NAV v2 step-1）—— count 源切到 EDGAR XBRL 后的三条分支。

守：① 单币成功 → EDGAR 一手单位数 × 实时币价算出 NAV，holdings.as_of=申报期末。
    ② 多币(is_crypto_filer=True 但 count=None) → applicable=False + reason 推 step-2，绝不出 NAV 数字。
    ③ 无 tag(is_crypto_filer=False) + 经营型 → operating，不出 NAV（同 v1）。
币价仍走 _CRYPTO.coin_price(yfinance)；测试全 stub，零网络、零 LLM。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import stages
from proto.state import ResearchState


class _StubEdgar:
    def __init__(self, ret): self._ret = ret
    def crypto_units(self, ticker): return self._ret


class _StubCryptoPrice:
    _PRICES = {"bitcoin": 60000.0, "ethereum": 3000.0}
    def coin_price(self, coin): return {"price": self._PRICES.get(coin, 100.0), "source": f"yfinance {coin}", "as_of": "2026-07-02"}
    def holdings(self, ticker): return None


class _StubIXBRL:
    def __init__(self, ret): self._ret = ret
    def crypto_units_by_coin(self, ticker): return self._ret


def _state(ticker, fundamentals):
    return ResearchState(ticker=ticker, raw_data={
        "fundamentals": fundamentals, "shares_outstanding": 250_000_000, "price": 400.0,
    })


def test_single_coin_success_computes_nav(monkeypatch):
    monkeypatch.setattr(stages, "_EDGAR_XBRL", _StubEdgar({
        "coin": "bitcoin", "count": 762099, "as_of": "2026-03-31",
        "source": "SEC EDGAR XBRL CryptoAssetNumberOfUnits (10-Q 2026-03-31)",
        "accn": "x", "is_crypto_filer": True}), raising=False)
    monkeypatch.setattr(stages, "_CRYPTO", _StubCryptoPrice(), raising=False)

    nav = stages._build_nav(_state("MSTR", {"cash": 50e6, "total_debt": 100e6,
                                            "revenue": 5e8, "total_assets": 4e10}))
    assert nav["type"] == "crypto_treasury"
    assert nav["applicable"] is True
    assert nav["result"]["value"] is not None                 # NAV 算出来了
    assert nav["holdings"][0]["count"] == 762099
    assert nav["holdings"][0]["as_of"] == "2026-03-31"         # 申报期末，非实时
    assert "EDGAR" in nav["holdings"][0]["source"]


def test_multicoin_step2_computes_nav(monkeypatch):
    # step-1 判多币(Integer) → 触发 step-2 iXBRL 拆出 BTC+ETH → 多币求和算 NAV
    monkeypatch.setattr(stages, "_EDGAR_XBRL", _StubEdgar({
        "count": None, "is_crypto_filer": True, "reason": "多币需 step-2"}), raising=False)
    monkeypatch.setattr(stages, "_EDGAR_IXBRL", _StubIXBRL({
        "coins": [{"coin": "bitcoin", "count": 195}, {"coin": "ethereum", "count": 4473459}],
        "as_of": "2026-02-28", "source": "SEC EDGAR 10-Q iXBRL (period 2026-02-28)", "accn": "x"}), raising=False)
    monkeypatch.setattr(stages, "_CRYPTO", _StubCryptoPrice(), raising=False)

    nav = stages._build_nav(_state("BMNR", {"cash": 1e8, "total_debt": 5e7,
                                            "revenue": 6e6, "total_assets": 8.8e9}))
    assert nav["type"] == "crypto_treasury" and nav["applicable"] is True
    got = {h["coin"]: h["count"] for h in nav["holdings"]}
    assert got == {"bitcoin": 195, "ethereum": 4473459}        # 两币都在，as_of 期末
    assert all(h["as_of"] == "2026-02-28" for h in nav["holdings"])
    # 加密总市值 = 195×60000 + 4,473,459×3000（多币求和，绝不漏币）
    assert abs(nav["crypto_value"]["value"] - (195 * 60000 + 4473459 * 3000)) < 1e-6
    assert nav["result"]["value"] is not None


def test_multicoin_step2_also_unattributable_data_insufficient(monkeypatch):
    # step-1 判多币 → step-2 也认不出(通用成员) → 数据不足，绝不出数字
    monkeypatch.setattr(stages, "_EDGAR_XBRL", _StubEdgar({
        "count": None, "is_crypto_filer": True, "reason": "多币需 step-2"}), raising=False)
    monkeypatch.setattr(stages, "_EDGAR_IXBRL", _StubIXBRL({
        "coins": None, "reason": "含无法归属的 CryptoAssetAxis 成员：整体判数据不足(窄版)"}), raising=False)
    monkeypatch.setattr(stages, "_CRYPTO", _StubCryptoPrice(), raising=False)

    nav = stages._build_nav(_state("XYZ", {"cash": 1e8, "total_debt": 5e7,
                                           "revenue": 6e6, "total_assets": 8.8e9}))
    assert nav["applicable"] is False
    assert "窄版" in nav["reason"] or "无法归属" in nav["reason"]
    assert "holdings" not in nav and "result" not in nav       # 绝不出 NAV 数字


def test_no_tag_operating_no_nav(monkeypatch):
    monkeypatch.setattr(stages, "_EDGAR_XBRL", _StubEdgar({
        "count": None, "is_crypto_filer": False, "reason": "非加密披露人"}), raising=False)
    monkeypatch.setattr(stages, "_CRYPTO", _StubCryptoPrice(), raising=False)

    nav = stages._build_nav(_state("AAPL", {"cash": 5e10, "total_debt": 1e11,
                                            "revenue": 4e11, "total_assets": 3.5e11}))
    assert nav["type"] == "operating"
    assert nav["applicable"] is False
    assert "holdings" not in nav
