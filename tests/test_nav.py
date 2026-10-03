"""
NAV(资产净值)估值纯函数单测 —— 针对资产持有型壳(v1: BTC/ETH 国库股)。

守死红线(决定这个功能诚实还是骗人)：
  · NAV 每个输入都必须是真实数据；任一缺失 → 返回 {"value": None, "reason": ...}，**绝不编一个数字**。
  · 口径选最严：现金/总债务任一缺失 → 整块"数据不足"，**绝不给"未扣负债的毛 NAV"**(会高估、误导)。
  · holdings_count(持仓量)缺失 → 数据不足，**绝不用 LLM 记忆补持仓数**。
  · 判定要确定性、可测：是不是资产持有型/哪一类/能不能算 NAV。
纯函数、零 LLM、零网络。不碰冻结的 tools/(含 method_router)与 105 回归。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import nav


# ─────────────── 多币持仓求和：一家公司可同时持多种币，必须全部计入 ───────────────
def test_crypto_holdings_value_sums_all_coins():
    # BMNR 式：同时持 BTC + ETH，两者都要计入，绝不只取第一个
    positions = [{"coin": "bitcoin", "count": 100, "price": 60000.0},
                 {"coin": "ethereum", "count": 1000, "price": 1600.0}]
    r = nav.crypto_holdings_value(positions)
    assert abs(r["value"] - (100 * 60000 + 1000 * 1600)) < 1e-6   # 6,000,000 + 1,600,000
    assert len(r["breakdown"]) == 2


def test_crypto_holdings_value_missing_count_is_na_no_undercount():
    # 任一币持仓数缺 → 整体数据不足，绝不漏算那一币导致低估(误导)
    positions = [{"coin": "ethereum", "count": None, "price": 1600.0}]
    r = nav.crypto_holdings_value(positions)
    assert r["value"] is None
    assert not isinstance(r["value"], (int, float))
    assert "ethereum" in r["reason"]


def test_crypto_holdings_value_missing_price_is_na():
    positions = [{"coin": "bitcoin", "count": 100, "price": None}]
    r = nav.crypto_holdings_value(positions)
    assert r["value"] is None and "bitcoin" in r["reason"]


# ─────────────── NAV 计算：齐全→精确(crypto_value 为多币求和后的总市值) ───────────────
def test_nav_per_share_exact_with_premium():
    # 加密总市值 2,000,000 + 现金 500,000 − 债务 100,000 = 2,400,000 / 股 1,000,000 = $2.40
    # 现价 3.00 → 溢价 3/2.4 − 1 = 25%
    r = nav.nav_per_share(crypto_value=2_000_000, cash=500_000, total_debt=100_000,
                          shares=1_000_000, current_price=3.00)
    assert abs(r["value"] - 2.40) < 1e-9
    assert abs(r["net_asset_value"] - 2_400_000) < 1e-6
    assert abs(r["premium_discount"] - 0.25) < 1e-9   # 现价溢价 25%
    assert r["source_kind"] == "computed"


def test_nav_per_share_discount_when_price_below_nav():
    r = nav.nav_per_share(crypto_value=2_000_000, cash=500_000, total_debt=100_000,
                          shares=1_000_000, current_price=1.80)
    assert r["premium_discount"] < 0          # 现价 1.80 < NAV 2.40 → 折价
    assert abs(r["premium_discount"] - (1.80 / 2.40 - 1)) < 1e-9


def test_nav_per_share_no_current_price_still_gives_nav_but_no_premium():
    r = nav.nav_per_share(crypto_value=2_000_000, cash=500_000, total_debt=100_000,
                          shares=1_000_000, current_price=None)
    assert abs(r["value"] - 2.40) < 1e-9       # NAV 本身能算
    assert r["premium_discount"] is None       # 但溢价折价缺现价 → None，不编


# ─────────────── 边界：任一关键输入缺失 → 数据不足、断言不是数字 ───────────────
def test_nav_missing_crypto_value_is_na_never_fabricated():
    # crypto_value 为 None 表示持仓/币价没拿全(上游已判数据不足)→ 绝不补一个数字
    r = nav.nav_per_share(crypto_value=None, cash=500_000, total_debt=100_000,
                          shares=1_000_000, current_price=3.0)
    assert r["value"] is None
    assert not isinstance(r["value"], (int, float))
    assert r["reason"]


def test_nav_missing_cash_is_na_no_gross_nav():
    # 最严口径：现金缺 → 整块数据不足，绝不给"未扣负债的毛 NAV"
    r = nav.nav_per_share(crypto_value=2_000_000, cash=None, total_debt=100_000,
                          shares=1_000_000, current_price=3.0)
    assert r["value"] is None
    assert not isinstance(r["value"], (int, float))
    assert "现金" in r["reason"] or "cash" in r["reason"]


def test_nav_missing_total_debt_is_na_no_gross_nav():
    r = nav.nav_per_share(crypto_value=2_000_000, cash=500_000, total_debt=None,
                          shares=1_000_000, current_price=3.0)
    assert r["value"] is None
    assert "债务" in r["reason"] or "debt" in r["reason"]


def test_nav_zero_or_missing_shares_is_na():
    assert nav.nav_per_share(2_000_000, 500_000, 100_000, shares=0, current_price=3.0)["value"] is None
    assert nav.nav_per_share(2_000_000, 500_000, 100_000, shares=None, current_price=3.0)["value"] is None


# ─────────────── 判定：是不是资产持有型 / 哪一类 / 能不能算 NAV ───────────────
def test_classify_crypto_treasury_when_in_treasury_list():
    hit = {"coin": "ethereum", "count": 5_700_040, "source": "CoinGecko public_treasury", "as_of": "2026-06-29"}
    c = nav.classify_asset_holder("BMNR", fundamentals={"revenue": 6e6, "total_assets": 8.8e9}, treasury_hit=hit)
    assert c["type"] == "crypto_treasury"
    assert c["nav_applicable"] is True


def test_classify_suspected_asset_holder_when_assets_dwarf_operations_but_no_holdings():
    # 资产远大于经营但拿不到持仓明细 → 疑似资产持有型，NAV 不适用(不硬算)
    c = nav.classify_asset_holder("XYZ", fundamentals={"revenue": 6e6, "total_assets": 8.8e9}, treasury_hit=None)
    assert c["type"] == "suspected_asset_holder"
    assert c["nav_applicable"] is False
    assert c["reason"]


def test_classify_operating_company_no_nav_block():
    # AAPL：营收对总资产并不微小 → 经营型，不出 NAV 区块
    c = nav.classify_asset_holder("AAPL", fundamentals={"revenue": 416e9, "total_assets": 359e9}, treasury_hit=None)
    assert c["type"] == "operating"
    assert c["nav_applicable"] is False
