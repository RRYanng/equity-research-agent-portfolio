"""
估值方法路由(#1) —— 纯函数，零 LLM。

落实 blueprint Phase 5 的"自动选方法"，并堵住原型暴露的硬伤：
FCF<=0 时 DCF 在数学上符号反转(增长越高估值越低)，必须关掉 DCF，改走倍数/Rule-of-40。
"""
from __future__ import annotations


def select_valuation_method(base_fcf, net_income) -> dict:
    """
    路由规则：
      - base_fcf <= 0  → DCF 关闭(硬闸)，走 multiples。DCF 对非正现金流无定义。
      - base_fcf > 0 但未盈利(NI<=0) → 允许 DCF 但 low_confidence，必须靠倍数交叉。
      - 正 FCF 且盈利 → DCF 适用(主镜头)。
    """
    if base_fcf is None or base_fcf <= 0:
        return {
            "method": "multiples", "dcf_eligible": False, "low_confidence": True,
            "reason": "FCF<=0：DCF 对非正现金流无定义(会符号反转)，改走倍数 + Rule-of-40 + 现金 runway",
        }
    if net_income is None or net_income <= 0:
        return {
            "method": "dcf", "dcf_eligible": True, "low_confidence": True,
            "reason": "正 FCF 但未盈利：DCF 低置信，必须用倍数交叉验证，不可单独定评级",
        }
    return {
        "method": "dcf", "dcf_eligible": True, "low_confidence": False,
        "reason": "正 FCF 且盈利：DCF 适用为主镜头(仍与倍数交叉)",
    }
