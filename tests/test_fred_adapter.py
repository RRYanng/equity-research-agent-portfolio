"""
FredAdapter 单测（Phase 3 · FRED 接入）—— 注入假 HTTP，离线跑，不碰真网络。

守：① 正常 JSON → 正确委托纯函数 + 单位换算（UNRATE/DGS 百分比 → 小数）。
    ② 无 key / HTTP 失败 → 每个指标返回 {"value": None, "reason"}，绝不崩、绝不编。
    ③ as_of 用 observation 所属期；DGS 跳过节假日 "." 取最新有效交易日。
"""
import sys
from numbers import Number
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.data.fred import FredAdapter

_CPI = {"observations": [
    {"date": "2026-05-01", "value": "320.0"},
    {"date": "2026-04-01", "value": "319.0"},
    {"date": "2025-05-01", "value": "310.0"},
]}
_UNRATE = {"observations": [{"date": "2026-06-01", "value": "4.1"}]}
_DGS2 = {"observations": [
    {"date": "2026-06-30", "value": "4.60"},
    {"date": "2026-06-29", "value": "."},          # 节假日缺失，跳过
]}
_DGS10 = {"observations": [{"date": "2026-06-30", "value": "4.30"}]}


def _fake_http(url):
    if "CPIAUCSL" in url:
        return _CPI
    if "UNRATE" in url:
        return _UNRATE
    if "series_id=DGS2&" in url or "series_id=DGS2&" in url or "DGS2" in url:
        return _DGS2
    if "DGS10" in url:
        return _DGS10
    raise AssertionError(f"unexpected url: {url}")


def _adapter(http=_fake_http, key="fake-key"):
    return FredAdapter(api_key=key, http_json=http, cache=False)


# ─────────────── 正常路径：委托 + 单位换算 ───────────────
def test_inflation_delegates_to_pure_fn():
    r = _adapter().inflation()
    assert r["value"] == round(320.0 / 310.0 - 1, 4)
    assert r["as_of"] == "2026-05"


def test_unemployment_percent_to_decimal():
    r = _adapter().unemployment()
    assert r["value"] == 0.041                       # 4.1% → 0.041
    assert r["as_of"] == "2026-06"
    assert "UNRATE" in r["source"]


def test_yield_curve_inverted_and_decimal():
    r = _adapter().yield_curve()
    # DGS2 4.60% → 0.046，DGS10 4.30% → 0.043（跳过 06-29 的 "."）
    assert r["dgs2"] == 0.046
    assert r["dgs10"] == 0.043
    assert r["spread"] == round(0.043 - 0.046, 4)
    assert r["inverted"] is True
    assert r["as_of"] == "2026-06-30"


# ─────────────── 红线：无 key / 失败 → 数据不足，绝不编 ───────────────
def test_no_key_all_none():
    a = FredAdapter(api_key=None, http_json=_fake_http, cache=False)
    for block in (a.inflation(), a.unemployment(), a.yield_curve()):
        assert block["value"] is None
        assert not isinstance(block["value"], Number)
        assert "reason" in block


def test_http_failure_returns_none_no_crash():
    def boom(url):
        raise ConnectionError("network down")
    a = _adapter(http=boom)
    for block in (a.inflation(), a.unemployment(), a.yield_curve()):
        assert block["value"] is None
        assert not isinstance(block["value"], Number)
    # 曲线缺腿时不能给毛价差
    assert "spread" not in a.yield_curve()
