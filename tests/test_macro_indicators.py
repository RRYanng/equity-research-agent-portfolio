"""
宏观指标纯函数单测（Phase 3 · FRED 接入）。

守死项目零伪造头号原则，与 quality.py / nav.py 同一标准：
  · 数据齐全 → 算出精确数字（断言具体数值）。
  · CPI 缺去年同月 / 收益率曲线缺任一腿 → 返回 {"value": None, "reason": ...}，
    **绝不返回一个编造的数字、绝不给毛价差**。
  · as_of 用 FRED observation 的所属期（不是运行日），缺失月（"."）跳过、取下一有效值。
纯函数、零 LLM、零网络。不触碰冻结的 tools/ 与 118 回归。
"""
import sys
from numbers import Number
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto import macro_indicators as mi


# ─────────────── latest_observation：跳过缺失、取最新有效 ───────────────
def test_latest_observation_picks_newest_valid():
    # 乱序 + 一个 "." 缺失；应返回最新的有效观测
    obs = [
        {"date": "2026-04-01", "value": "4.0"},
        {"date": "2026-06-01", "value": "."},      # 缺失，跳过
        {"date": "2026-05-01", "value": "4.1"},
    ]
    assert mi.latest_observation(obs) == ("2026-05-01", 4.1)


def test_latest_observation_all_missing_returns_none():
    obs = [{"date": "2026-05-01", "value": "."}, {"date": "2026-04-01", "value": "."}]
    assert mi.latest_observation(obs) is None


def test_latest_observation_empty_returns_none():
    assert mi.latest_observation([]) is None


# ─────────────── CPI → YoY 通胀（自算，可测） ───────────────
def test_yoy_inflation_computes_correct_rate():
    # 最新 2026-05 指数 320.0，去年同月 2025-05 指数 310.0 → 320/310-1 = 0.0323
    obs = [
        {"date": "2026-05-01", "value": "320.0"},
        {"date": "2026-04-01", "value": "319.0"},
        {"date": "2025-05-01", "value": "310.0"},
    ]
    r = mi.yoy_inflation(obs)
    assert r["value"] == round(320.0 / 310.0 - 1, 4)   # 0.0323
    assert r["as_of"] == "2026-05"                     # 所属月，非运行日
    assert "CPIAUCSL" in r["source"]


def test_yoy_inflation_missing_prior_year_returns_none():
    # 只有最新月、没有去年同月 → 不能算 YoY，返回 None，绝不编
    obs = [{"date": "2026-05-01", "value": "320.0"}, {"date": "2026-04-01", "value": "319.0"}]
    r = mi.yoy_inflation(obs)
    assert r["value"] is None
    assert not isinstance(r["value"], Number)          # 红线：不是数字
    assert "reason" in r


def test_yoy_inflation_empty_returns_none():
    r = mi.yoy_inflation([])
    assert r["value"] is None
    assert not isinstance(r["value"], Number)


def test_yoy_inflation_skips_missing_latest_dot():
    # 最新月是 "." → 用下一有效月为"最新"，as_of 随之
    obs = [
        {"date": "2026-05-01", "value": "."},
        {"date": "2026-04-01", "value": "318.0"},
        {"date": "2025-04-01", "value": "309.0"},
    ]
    r = mi.yoy_inflation(obs)
    assert r["value"] == round(318.0 / 309.0 - 1, 4)
    assert r["as_of"] == "2026-04"


# ─────────────── 收益率曲线 2s10s：价差 + 倒挂（自算，可测） ───────────────
def test_curve_state_normal_not_inverted():
    dgs2 = {"value": 0.043, "as_of": "2026-06-30"}
    dgs10 = {"value": 0.045, "as_of": "2026-06-30"}
    r = mi.curve_state(dgs2, dgs10)
    assert r["spread"] == round(0.045 - 0.043, 4)      # +0.002
    assert r["inverted"] is False
    assert r["as_of"] == "2026-06-30"


def test_curve_state_inverted_when_2y_above_10y():
    dgs2 = {"value": 0.046, "as_of": "2026-06-30"}
    dgs10 = {"value": 0.043, "as_of": "2026-06-30"}
    r = mi.curve_state(dgs2, dgs10)
    assert r["spread"] == round(0.043 - 0.046, 4)      # -0.003
    assert r["inverted"] is True


def test_curve_state_missing_10y_returns_none():
    # 缺一腿 → 整块数据不足，绝不给毛价差
    r = mi.curve_state({"value": 0.046, "as_of": "2026-06-30"}, None)
    assert r["value"] is None
    assert not isinstance(r["value"], Number)
    assert "spread" not in r                            # 红线：不给假价差
    assert "reason" in r


def test_curve_state_missing_2y_returns_none():
    r = mi.curve_state(None, {"value": 0.045, "as_of": "2026-06-30"})
    assert r["value"] is None
    assert "spread" not in r


def test_curve_state_none_value_leg_returns_none():
    # 腿存在但 value 为 None（FRED 返回但值缺）→ 同样数据不足
    r = mi.curve_state({"value": None, "as_of": "2026-06-30"},
                       {"value": 0.045, "as_of": "2026-06-30"})
    assert r["value"] is None
    assert "spread" not in r
