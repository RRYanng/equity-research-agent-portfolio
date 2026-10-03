"""
FinnhubAdapter（size-matched peer-median 主镜头）+ 三方组合（Phase 1 step 3）。

设计（已锁定）：
  · Finnhub peer-median = 主镜头（给 megacap 定价最贴切，纠 Damodaran 行业聚合偏高的偏差）
  · Damodaran 行业 = 参照
  · 两源分歧 → 降置信（复用 #5 那套）
  · 三级降级：Finnhub 空/限流 → Damodaran → 都没有才退 LLM 估算并标 low_confidence

口径（TTM，最易错处）：
  · Finnhub peTTM = P/E，与 tools/comparables 的 "pe" 槽（price/eps）口径一致 → 作主倍数。
  · Finnhub psTTM = P/S（市值/营收），≠ EV/Sales，绝不喂进 comparables 的 ev_sales 槽
    （会重复扣净负债）；只留作参考。EV/Sales 维度用 Damodaran 的真 EV/Sales。
  · 三方全部 TTM。

本模块只【读取】tools/comparables，绝不修改它。
"""
from __future__ import annotations

import statistics

from ..tools import comparables


# ───────────────────────── Finnhub 实现（client 可注入，便于 mock 测试） ─────────────────────────
class FinnhubAdapter:
    SOURCE = "Finnhub peer-median (TTM)"

    def __init__(self, api_key: str | None = None, client=None, max_peers: int = 12):
        self._api_key = api_key
        self._client = client            # 测试注入 fake；生产为 None 时懒创建
        self._max_peers = max_peers

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise RuntimeError("FINNHUB_API_KEY 未设置")
        import finnhub  # 懒 import，mock 测试无需装 finnhub
        self._client = finnhub.Client(api_key=self._api_key)
        return self._client

    @staticmethod
    def _band(values) -> dict | None:
        """从一组正倍数算 25/50/75 分位带。空→None；单值→三分位都取该值。"""
        vs = sorted(v for v in values if isinstance(v, (int, float)) and v > 0)
        if not vs:
            return None
        if len(vs) == 1:
            return {"p25": vs[0], "median": vs[0], "p75": vs[0], "n": 1}
        q = statistics.quantiles(vs, n=4)   # [Q1, Q2, Q3]
        return {"p25": round(q[0], 2), "median": round(statistics.median(vs), 2),
                "p75": round(q[2], 2), "n": len(vs)}

    def get_peer_multiples(self, ticker: str) -> dict | None:
        """
        取 size/sector 匹配同业 → 每个 peer 的 peTTM / psTTM → 分位带。
        失败/空 → None（让上游降级，不让链崩、不伪造）。排除标的自身。
        """
        try:
            client = self._get_client()
            peers = [p for p in (client.company_peers(ticker) or []) if p != ticker][: self._max_peers]
            if not peers:
                return None
            pes, pss = [], []
            for p in peers:
                metric = (client.company_basic_financials(p, "all") or {}).get("metric", {}) or {}
                pe, ps = metric.get("peTTM"), metric.get("psTTM")
                if isinstance(pe, (int, float)) and pe > 0:
                    pes.append(pe)
                if isinstance(ps, (int, float)) and ps > 0:
                    pss.append(ps)
            pe_band, ps_band = self._band(pes), self._band(pss)
            if pe_band is None and ps_band is None:
                return None
            return {
                "peers": peers, "n_peers": len(peers),
                "pe_band": pe_band,         # 主用：与 comparables "pe" 口径一致
                "ps_band": ps_band,         # 仅参考：P/S ≠ EV/Sales，不喂 comparables
                "source": self.SOURCE, "basis": "TTM",
            }
        except Exception:  # noqa: BLE001 — 数据源失败要降级
            return None


# ───────────────────────── 由 fair 倍数算 verdict（桥接 tools，只读） ─────────────────────────
def verdict_from_fair_multiples(price, eps, revenue, shares, net_debt, fm_lo: dict, fm_hi: dict) -> str | None:
    """
    用一组(下界/上界)fair 倍数，经 tools.comparables 算隐含价值带 → 现价相对位置 verdict。
    与现有 _fair_multiples_lens 同一套口径。fm_lo/fm_hi 形如 {"pe":x, "ev_sales":y}。
    """
    lo = comparables.comparables_valuation(
        eps if (eps and eps > 0) else None, None, revenue, shares, net_debt, fm_lo)
    hi = comparables.comparables_valuation(
        eps if (eps and eps > 0) else None, None, revenue, shares, net_debt, fm_hi)
    lows = [v for v in lo["implied_values"].values() if v is not None]
    highs = [v for v in hi["implied_values"].values() if v is not None]
    if not (lows or highs):
        return None
    band = (min(lows + highs), max(lows + highs))
    return comparables.price_vs_band(price, band)


# ───────────────────────── 三方组合：分歧降置信 + 三级降级（纯逻辑核心） ─────────────────────────
def combine_verdicts(finnhub_verdict, damodaran_verdict, llm_verdict) -> dict | None:
    """
    组合三个来源的 verdict（cheap/fair/expensive 或 None）。这是 step3 的逻辑核心：
      · Finnhub 有 → 主镜头；若 Damodaran 也有且不一致 → low_confidence（分歧降置信）。
      · Finnhub 无 → 降级 Damodaran（real，不 low_confidence）。
      · 两真源都无 → 降级 LLM 估算，low_confidence=True（三级降级末级）。
      · 全无 → None。
    """
    if finnhub_verdict is not None:
        agree = (finnhub_verdict == damodaran_verdict) if damodaran_verdict is not None else None
        return {
            "source": "finnhub", "mult_verdict": finnhub_verdict,
            "low_confidence": agree is False,           # 仅"明确分歧"才降置信
            "cross_check": {"finnhub": finnhub_verdict, "damodaran": damodaran_verdict, "agree": agree},
        }
    if damodaran_verdict is not None:
        return {
            "source": "damodaran", "mult_verdict": damodaran_verdict, "low_confidence": False,
            "cross_check": {"finnhub": None, "damodaran": damodaran_verdict, "agree": None},
        }
    if llm_verdict is not None:
        return {
            "source": "llm_estimate", "mult_verdict": llm_verdict, "low_confidence": True,
            "cross_check": {"finnhub": None, "damodaran": None, "agree": None},
        }
    return None
