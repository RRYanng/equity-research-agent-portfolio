"""
评测集 rubric（Phase 9 ③）：5 个合成路由案例的"该有的关键结论"。

只断言【稳定属性】(评级方向/置信/分流/无编造)——这些由确定性逻辑(tier 判级/方法路由/
评级规则/PRE_IPO 降级)决定，LLM 叙事抖动不会让它们翻。所以 replay/live 都能稳定打分。

每个 rubric: (state) -> list[(check_name, passed_bool)]。
"""
from __future__ import annotations


def _md_finnhub(vv):
    return (vv.multiples_detail or {}).get("finnhub") or {}


def rubric_AAPL(state):
    m, vv = state.memo, state.valuation_view
    return [
        ("tier=public", state.tier.value == "public"),
        ("走 DCF 分流", m.valuation_method == "dcf"),
        ("评级=Hold(非自信Sell)", m.rating == "Hold"),
        ("置信=low", m.confidence == "low"),
        ("DCF 镜头=expensive", vv.dcf_verdict == "expensive"),
        ("Synthetic peer band=fair", _md_finnhub(vv).get("verdict") == "fair"),
        ("EV is numeric for synthetic inputs", isinstance(m.expected_value_per_share, (int, float))),
    ]


def rubric_MSFT(state):
    m, vv = state.memo, state.valuation_view
    return [
        ("tier=public", state.tier.value == "public"),
        ("走 DCF 分流", m.valuation_method == "dcf"),
        ("评级=Hold", m.rating == "Hold"),
        ("置信=low", m.confidence == "low"),
        ("DCF 镜头=expensive", vv.dcf_verdict == "expensive"),
    ]


def rubric_AI(state):   # C3.ai
    m, vv = state.memo, state.valuation_view
    neg = [s.per_share_value for s in vv.scenarios if s.per_share_value is not None and s.per_share_value < 0]
    return [
        ("tier=public", state.tier.value == "public"),
        ("DCF 被路由关闭", vv.dcf_disabled is True),
        ("走倍数法分流", m.valuation_method == "multiples"),
        ("无负的每股内在价值(无符号反转)", len(neg) == 0),
    ]


def rubric_SPACEX(state):
    m, vv = state.memo, state.valuation_view
    return [
        ("tier=pre_ipo", state.tier.value == "pre_ipo"),
        ("评级=数据不足", ("数据不足" in m.rating) or ("N/A" in m.rating)),
        ("EV=None(不编估值锚)", m.expected_value_per_share is None),
        ("method=insufficient_data", m.valuation_method == "insufficient_data"),
        ("无情景(不编 DCF)", len(vv.scenarios) == 0),
        ("置信=low", m.confidence == "low"),
    ]


def rubric_AABB(state):
    m, vv = state.memo, state.valuation_view
    f = state.raw_data.get("fundamentals", {})
    return [
        ("tier=pre_ipo", state.tier.value == "pre_ipo"),
        ("有的字段保留(价格非None)", state.raw_data.get("price") is not None),
        ("缺的财报标 None(revenue=None)", f.get("revenue") is None),
        ("评级=数据不足", ("数据不足" in m.rating) or ("N/A" in m.rating)),
        ("EV=None(不编)", m.expected_value_per_share is None),
    ]


CASES = {
    "AAPL": rubric_AAPL,
    "MSFT": rubric_MSFT,
    "AI": rubric_AI,
    "SPACEX": rubric_SPACEX,
    "AABB": rubric_AABB,
}
