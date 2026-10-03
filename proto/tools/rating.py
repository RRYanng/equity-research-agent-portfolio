"""
评级决策规则(#5) —— 纯函数，零 LLM。

核心修复："优质股 = 自信 Sell"的根因是单一 DCF 直接驱动评级。
这里改成：至少两条独立镜头(DCF + 倍数)，一致才高置信，分歧就降到 Hold/低置信。
DCF 被关掉(负 FCF)时，评级只能来自倍数，且置信度封顶。
"""
from __future__ import annotations

_VERDICT_TO_RATING = {"expensive": "Sell", "fair": "Hold", "cheap": "Buy"}


def decide_rating(dcf_verdict, mult_verdict, dcf_disabled: bool, dcf_gap=None) -> dict:
    """
    dcf_verdict / mult_verdict ∈ {"cheap","fair","expensive"}(估值偏贵=expensive=偏空)。
    返回 {rating, confidence, basis}。
    """
    # DCF 关闭：只信倍数(C3.ai 路径)，置信度封顶 low
    if dcf_disabled or dcf_verdict is None:
        rating = _VERDICT_TO_RATING.get(mult_verdict, "Hold")
        return {
            "rating": rating, "confidence": "low",
            "basis": f"DCF 已关闭(负/微 FCF，无定义)，评级来自倍数/Rule-of-40：{mult_verdict}",
        }

    # 两镜头一致 → 高置信(中性一致给 medium)
    if dcf_verdict == mult_verdict:
        conf = "high" if dcf_verdict in ("expensive", "cheap") else "medium"
        return {
            "rating": _VERDICT_TO_RATING[dcf_verdict], "confidence": conf,
            "basis": f"DCF 与倍数一致判定为 {dcf_verdict}",
        }

    # 两镜头分歧 → 不允许高置信单边，降到 Hold/低置信(这就是 AAPL/MSFT 的修复)
    return {
        "rating": "Hold", "confidence": "low",
        "basis": f"模型分歧：DCF={dcf_verdict} 但倍数={mult_verdict}；溢价更可能被 DCF 框架漏算，降置信至 Hold",
    }
