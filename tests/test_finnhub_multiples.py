"""
FinnhubAdapter + 三方组合 单测（Phase 1 step3，mock 阶段）。
零网络、零 key：注入 fake client。重点覆盖"两源分歧→降置信"和"三级降级"。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.data.multiples import FinnhubAdapter, combine_verdicts, verdict_from_fair_multiples


class FakeFinnhub:
    """模拟 finnhub.Client：company_peers + company_basic_financials。"""
    def __init__(self, peers, financials):
        self._peers, self._fin = peers, financials

    def company_peers(self, ticker):
        return self._peers

    def company_basic_financials(self, ticker, _freq):
        return {"metric": self._fin.get(ticker, {})}


# ───────────────── FinnhubAdapter：peer 分位带 + 自身排除 + 缺失/空降级 ─────────────────
def test_peer_band_excludes_self_and_computes_quantiles():
    client = FakeFinnhub(
        peers=["AAPL", "MSFT", "DELL", "HPQ"],
        financials={"MSFT": {"peTTM": 30, "psTTM": 12}, "DELL": {"peTTM": 20, "psTTM": 1},
                    "HPQ": {"peTTM": 10, "psTTM": 1}},
    )
    out = FinnhubAdapter(client=client).get_peer_multiples("AAPL")
    assert "AAPL" not in out["peers"] and out["n_peers"] == 3       # 排除自身
    assert out["pe_band"]["median"] == 20                          # median(10,20,30)
    assert out["pe_band"]["p25"] <= out["pe_band"]["median"] <= out["pe_band"]["p75"]
    assert out["basis"] == "TTM"


def test_peer_band_skips_missing_or_nonpositive_metrics():
    client = FakeFinnhub(
        peers=["X", "Y", "Z"],
        financials={"X": {"peTTM": 25}, "Y": {"peTTM": None}, "Z": {"peTTM": -5, "psTTM": 3}},
    )
    out = FinnhubAdapter(client=client).get_peer_multiples("TGT")
    assert out["pe_band"]["n"] == 1            # 只有 X 的 peTTM 有效
    assert out["ps_band"]["n"] == 1            # 只有 Z 的 psTTM 有效


def test_empty_peers_returns_none():
    client = FakeFinnhub(peers=[], financials={})
    assert FinnhubAdapter(client=client).get_peer_multiples("TGT") is None


def test_no_key_no_client_degrades_to_none():
    # 没 key、没注入 client → 取数失败但不崩，返回 None（让上游降级）
    assert FinnhubAdapter(api_key=None).get_peer_multiples("AAPL") is None


# ───────────────── 三方组合：分歧降置信 ─────────────────
def test_sources_agree_not_low_confidence():
    out = combine_verdicts("expensive", "expensive", None)
    assert out["source"] == "finnhub" and out["mult_verdict"] == "expensive"
    assert out["low_confidence"] is False and out["cross_check"]["agree"] is True


def test_sources_disagree_lowers_confidence():
    """核心：Finnhub 与 Damodaran 判定不一致 → 降置信（复用 #5 逻辑）。"""
    out = combine_verdicts("expensive", "cheap", None)
    assert out["source"] == "finnhub"            # 主镜头仍是 Finnhub
    assert out["low_confidence"] is True         # 但分歧 → 降置信
    assert out["cross_check"]["agree"] is False


def test_finnhub_only_not_low_confidence():
    out = combine_verdicts("fair", None, None)
    assert out["source"] == "finnhub" and out["low_confidence"] is False
    assert out["cross_check"]["agree"] is None


# ───────────────── 三方组合：三级降级 ─────────────────
def test_degrade_level2_finnhub_missing_use_damodaran():
    out = combine_verdicts(None, "fair", "expensive")
    assert out["source"] == "damodaran" and out["mult_verdict"] == "fair"
    assert out["low_confidence"] is False        # Damodaran 是真数据，不降置信


def test_degrade_level3_both_real_missing_use_llm_low_confidence():
    out = combine_verdicts(None, None, "expensive")
    assert out["source"] == "llm_estimate" and out["mult_verdict"] == "expensive"
    assert out["low_confidence"] is True         # 退到 LLM 估算 → 必降置信


def test_degrade_all_missing_returns_none():
    assert combine_verdicts(None, None, None) is None


# ───────────────── 口径桥接：fair 倍数 → verdict（经 comparables，只读） ─────────────────
def test_verdict_from_fair_multiples_positions():
    # eps=10, fair PE 带 15–20 → 隐含每股 150–200
    args = dict(eps=10.0, revenue=1000.0, shares=100.0, net_debt=0.0,
                fm_lo={"pe": 15}, fm_hi={"pe": 20})
    assert verdict_from_fair_multiples(price=300, **args) == "expensive"   # 现价高于带
    assert verdict_from_fair_multiples(price=100, **args) == "cheap"       # 低于带
    assert verdict_from_fair_multiples(price=175, **args) == "fair"        # 带内
