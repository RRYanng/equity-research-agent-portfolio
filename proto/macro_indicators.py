"""
宏观指标纯函数（Phase 3 · FRED 接入）—— 零网络、零 LLM，只做确定性计算。

I/O 在 proto/data/fred.py（拉 FRED observations）；这里只负责：
  · latest_observation：跳过缺失（"."）、取最新有效观测。
  · yoy_inflation：CPI 指数 → 同比通胀率（本月/去年同月 − 1），自算而非用 FRED 预算值。
  · curve_state：2Y/10Y 收益率 → 价差 + 倒挂判定，自算。

诚实红线（与 quality.py / nav.py 同标准）：
  数据不足（CPI 缺去年同月 / 曲线缺任一腿）→ 返回 {"value": None, "reason": ...}，
  **绝不返回编造数字、绝不给毛价差**。as_of 一律用 observation 所属期，不用运行日。
"""
from __future__ import annotations

_MISSING = (None, ".", "")


def _parse(observations) -> list[tuple[str, float]]:
    """FRED obs list → [(date, value)] 仅有效值，按日期降序（最新在前）。"""
    out: list[tuple[str, float]] = []
    for o in observations or []:
        v = o.get("value")
        if v in _MISSING:
            continue
        try:
            out.append((o.get("date"), float(v)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def latest_observation(observations):
    """最新有效观测 (date, value)；全缺失/空 → None。"""
    obs = _parse(observations)
    return obs[0] if obs else None


def _minus_one_year(date_str: str) -> str:
    """月度 CPI 日期恒为 YYYY-MM-01，去年同月 = 年份减一。"""
    y, rest = date_str.split("-", 1)
    return f"{int(y) - 1}-{rest}"


def yoy_inflation(cpi_observations) -> dict:
    """CPI 指数序列 → 同比通胀率（小数，如 0.032）。缺去年同月则数据不足。"""
    obs = _parse(cpi_observations)
    if not obs:
        return {"value": None, "reason": "FRED 未返回有效 CPI 观测"}
    latest_date, latest_val = obs[0]
    prior_date = _minus_one_year(latest_date)
    prior_val = dict(obs).get(prior_date)
    if prior_val in _MISSING or prior_val is None:
        return {"value": None, "reason": f"缺 {prior_date[:7]} 同月 CPI，无法算 YoY"}
    return {
        "value": round(latest_val / prior_val - 1, 4),
        "as_of": latest_date[:7],                       # 所属月 YYYY-MM
        "latest_index": latest_val, "prior_index": prior_val,
        "source": "FRED CPIAUCSL（YoY 自算）",
    }


def _has_val(leg) -> bool:
    return bool(leg) and leg.get("value") is not None


def curve_state(dgs2, dgs10) -> dict:
    """2Y/10Y 收益率（各为 {value, as_of} 或 None）→ 价差 + 倒挂。缺任一腿 → 数据不足。"""
    if not _has_val(dgs2) or not _has_val(dgs10):
        return {"value": None, "reason": "2Y 或 10Y 收益率数据不足"}
    v2, v10 = dgs2["value"], dgs10["value"]
    spread = round(v10 - v2, 4)
    return {
        "dgs2": v2, "dgs10": v10, "spread": spread, "inverted": spread < 0,
        "as_of": dgs10.get("as_of") or dgs2.get("as_of"),
        "source": "FRED DGS2/DGS10（价差自算）",
    }
