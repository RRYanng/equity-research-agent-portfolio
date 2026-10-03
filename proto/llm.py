"""
Claude 调用封装 + 模型路由 + 结构化输出 + token 成本追踪。

模型分配 (README.md)：常规分析节点用 Sonnet 控成本；
Risk 红队和 Committee 用 Opus 做强对抗/综合推理。

结构化输出：用"强制 tool use"拿干净 JSON —— 给 Claude 一个 output schema 工具，
tool_choice 强制它调用，从 tool_use.input 直接取结构化结果，不靠解析自由文本。

LLM 只解读，绝不算账(原则 3)：本模块只负责把"数字+上下文"喂进去、把"解读"取出来。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
import anthropic

load_dotenv(Path(__file__).resolve().parent / ".env")

OPUS = "claude-opus-4-8"
SONNET = "claude-sonnet-4-6"

# 粗略价格(美元/百万 token)，仅供原型成本感知，非账单 (sonnet 3/15, opus 15/75)
_PRICE = {
    SONNET: (3.0, 15.0),
    OPUS: (15.0, 75.0),
}

_client = None
_usage = {"input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0.0, "calls": 0}
_ceiling: float | None = None   # 单次 run 的硬成本上限(USD)。None=不限。


class CostCeilingExceeded(Exception):
    """全链路成本逼近上限时抛出。硬停信号——绝不能被节点熔断的 try/except 吞掉。"""


def set_cost_ceiling(usd: float | None) -> None:
    """设单次 run 的硬成本上限(USD)。run 开头调用。"""
    global _ceiling
    _ceiling = usd


def reset_usage() -> None:
    """清零成本累计。每次 run 开头调用(上限是单次 run 的，不是进程累计)。"""
    _usage.update({"input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0.0, "calls": 0})


def _estimate_next_cost(model: str, system: str, user: str, max_tokens: int) -> float:
    """
    保守预估下一次调用成本(USD)。输出按 max_tokens 上界(实际≤它)，输入按字符数/1.5 估
    (中文最坏约 1.5 char/tok，偏高估)。宁可略高估早停，保证"预调用闸"永不真超上限。
    """
    pin, pout = _PRICE.get(model, (0, 0))
    est_in_tokens = (len(system) + len(user)) / 1.5
    return est_in_tokens / 1e6 * pin + max_tokens / 1e6 * pout


def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 未设置。请把 key 放进 proto/.env："
                "\n  ANTHROPIC_API_KEY=sk-ant-..."
            )
        # 节点级超时 + 封顶重试(不无限重试)：护栏的一部分
        _client = anthropic.Anthropic(api_key=key, timeout=120.0, max_retries=2)
    return _client


def _track(model: str, usage):
    pin, pout = _PRICE.get(model, (0, 0))
    cost = usage.input_tokens / 1e6 * pin + usage.output_tokens / 1e6 * pout
    _usage["input_tokens"] += usage.input_tokens
    _usage["output_tokens"] += usage.output_tokens
    _usage["est_cost_usd"] += cost
    _usage["calls"] += 1


def usage_summary() -> dict:
    return dict(_usage)


def _cost_gate(model: str, system: str, user: str, max_tokens: int) -> None:
    """预调用闸：发请求前检查"已花 + 本次保守预估 > 上限"，是则硬停(请求根本不发)。"""
    if _ceiling is None:
        return
    est = _estimate_next_cost(model, system, user, max_tokens)
    if _usage["est_cost_usd"] + est > _ceiling:
        raise CostCeilingExceeded(
            f"触及成本上限 ${_ceiling:.2f}：已花 ${_usage['est_cost_usd']:.3f} + 本次预估 ${est:.3f} "
            f"将超限，已停(本次请求未发出)。"
        )


import json


def _coerce_json_fields(data: dict, schema: dict) -> dict:
    """
    结构化输出健壮性：模型偶尔把 object/array 字段塞成 JSON 字符串。
    按 schema 声明的类型，把这类字符串 json.loads 回来。集中处理一次，所有节点受益。
    """
    if not isinstance(data, dict):
        return data
    props = schema.get("properties", {})
    for k, spec in props.items():
        t = spec.get("type")
        v = data.get(k)
        if t in ("object", "array") and isinstance(v, str):
            try:
                data[k] = json.loads(v)
            except (ValueError, TypeError):
                pass
    return data


def _missing_required(data: dict, schema: dict) -> list[str]:
    return [k for k in schema.get("required", []) if k not in data]


def _fill_defaults(data: dict, schema: dict) -> dict:
    """补齐模型偶尔漏掉的 required 字段，按类型给安全默认值，避免整条链因一个缺字段崩。"""
    props = schema.get("properties", {})
    for k in _missing_required(data, schema):
        t = props.get(k, {}).get("type")
        data[k] = {"string": "(模型未提供)", "array": [], "object": {}, "number": 0}.get(t, "(模型未提供)")
    return data


def _emit_once(client, model, system, user, schema, tool_name, max_tokens) -> dict:
    _cost_gate(model, system, user, max_tokens)   # 预调用闸：每次真实 API 调用前都查(含重试)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[{
            "name": tool_name,
            "description": "把你的结构化分析结论填进这个 schema 返回。所有 required 字段必须填全。",
            "input_schema": schema,
        }],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}],
    )
    _track(model, resp.usage)
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise RuntimeError(f"模型未按预期调用工具 {tool_name}")


def call_structured(
    model: str,
    system: str,
    user: str,
    schema: dict,
    tool_name: str = "emit",
    max_tokens: int = 2000,
) -> dict:
    """
    强制结构化输出：定义一个 input_schema=schema 的工具，强制模型调用它，返回结构化 dict。
    护栏：若漏了 required 字段，重试一次(明确点名要补)，仍缺则填默认值，保证链不中断。
    """
    client = _get_client()
    out = _coerce_json_fields(_emit_once(client, model, system, user, schema, tool_name, max_tokens), schema)
    missing = _missing_required(out, schema)
    if missing:
        retry_user = user + f"\n\n上一次输出漏了这些必填字段：{missing}。请重新输出，把所有 required 字段填全。"
        out = _coerce_json_fields(_emit_once(client, model, system, retry_user, schema, tool_name, max_tokens), schema)
        out = _fill_defaults(out, schema)
    return out
