"""
9 个 stage 函数 —— 线性研究链 (macro→industry→company→financial→valuation→catalyst→risk→committee→memo)。

设计契约(为将来迁移 LangGraph)：每个 stage 形如
    def xxx_stage(state: ResearchState) -> dict   # 返回对 state 的更新
这正是 LangGraph 节点 `node(state)->partial_state` 的形状。
run.py 负责把返回的更新合并进 state，stage 之间绝不互相直接调用(原则：节点不绕过 state)。

铁律落地：
 - 估值/ROE/期望值全部走 tools/ 纯函数，LLM 只解读 (原则 3)。
 - 折现率：macro 给市场基准(β=1)，valuation 用 β 调整后的 cost of equity (用户修改 1)。
 - Industry 只吃 ticker 的 sector/industry，不依赖 company 产出，保持单向无环 (用户修改 2)。
 - financial / company 都带"相比上期/趋势"的边际判断 (用户修改 3，原则 2)。
"""
from __future__ import annotations

from .state import (
    ResearchState, DataTier, MacroView, IndustryView, CompanyView, FinancialView,
    ValuationView, ValuationScenario, Catalyst, RiskView, InvestmentMemo,
    PositionRules, Citation,
)
import os

from .tools import dcf, dupont, ratios, comparables, method_router, rating
from . import quality as quality_metrics
from . import nav as nav_calc
from .data.crypto import CryptoTreasuryAdapter
from .data.fred import FredAdapter
from .data.edgar_xbrl import EdgarCryptoAdapter
from .data.edgar_ixbrl import EdgarDimCryptoAdapter
from .data.edgar import EdgarTierResolver
from .data.consensus_source import ConsensusAdapter
from . import macro_indicators as macro_ind
from . import consensus as consensus_calc
from .data.adapter import DataAdapter, CompositeAdapter
from .data.damodaran import DamodaranAdapter
from .data.multiples import FinnhubAdapter, combine_verdicts
from . import llm

# 全局假设：美股股权风险溢价。免费源拿不到，显式标为分析师假设(原则 4、5)。
EQUITY_RISK_PREMIUM = 0.055

# 默认数据源（#1 契约）：CompositeAdapter = yfinance(取数) + EDGAR(判级) 组合。换源只改这里。
_DEFAULT_ADAPTER: DataAdapter = CompositeAdapter()


def _preipo(state) -> bool:
    """是否 PRE_IPO/数据稀疏标的——触发"绝不伪造"降级：禁 LLM 估算，缺的标 None。"""
    return state.tier == DataTier.PRE_IPO or bool(state.raw_data.get("data_sparse"))


# PRE_IPO 数据稀疏标的：给定性 LLM 节点的铁律（禁编造财务数字）
_PREIPO_GUARD = (
    "\n【PRE_IPO 数据稀疏铁律】本标的无完整财报，严禁编造任何具体财务数字"
    "（营收/利润/FCF/估值/比率/增长率等）；缺数据处必须明确写'数据不足'；只做定性判断。"
)


def _guard(state, system: str) -> str:
    """PRE_IPO 时给 system prompt 追加"禁编造数字"铁律。"""
    return system + _PREIPO_GUARD if _preipo(state) else system
# 倍数三方交叉源（Phase1 step4）：Finnhub peer-median 主 · Damodaran 行业参照 · 分歧降置信
_DAMODARAN = DamodaranAdapter()
_FINNHUB = FinnhubAdapter(api_key=os.environ.get("FINNHUB_API_KEY"))
# NAV(资产净值)数据源：加密国库持仓(CoinGecko) + 币价(yfinance)。可被 eval harness 替身。
_CRYPTO = CryptoTreasuryAdapter()
# FRED 宏观指标源(Phase 3)：CPI/失业率/2Y·10Y。缺 key → 全数据不足。可被 eval harness 替身。
_FRED = FredAdapter(api_key=os.environ.get("FRED_API_KEY"))
# NAV v2 持仓源(EDGAR XBRL 一手单位数)：严格单币；多币/失败 → 数据不足。可被 eval harness 替身。
_EDGAR_XBRL = EdgarCryptoAdapter(cik_lookup=EdgarTierResolver().cik_for)
# NAV v2 step-2 多币源(原始 iXBRL 维度解析，窄版)：懒加载——只在 step-1 判多币时才下 1.5MB。
_EDGAR_IXBRL = EdgarDimCryptoAdapter(cik_lookup=EdgarTierResolver().cik_for)
# 市场共识信号源(Phase 5 诚实版)：Finnhub 评级趋势 + yfinance 短仓。缺 → 数据不足。可被 harness 替身。
_CONSENSUS = ConsensusAdapter(finnhub_api_key=os.environ.get("FINNHUB_API_KEY"))


def _build_nav(state) -> dict:
    """
    NAV 资产净值块(独立区块，仅资产持有型出现)。全确定性、零 LLM。

    NAV v2：持仓单位数(count)改由 EDGAR XBRL 一手直取(`_EDGAR_XBRL.crypto_units`，严格单币)，
    币价仍走 yfinance(`_CRYPTO.coin_price`)。口径 = 一手单位数(申报期末) × 实时币价。
      · 单币成功 → 算 NAV(现金/债务/股数任一缺 → proto.nav 最严口径整块"数据不足")。
      · 多币/uom 不可归属(is_crypto_filer=True 但 count=None) → 数据不足 + 推 step-2，绝不硬算
        (companyconcept 剥维度后的聚合数会重演 v1 多币张冠李戴 bug)。
      · 无 tag/无 CIK/网络失败(is_crypto_filer 非 True) → 落回经营/疑似判定(同 v1 非加密路径)。
    """
    rd = state.raw_data
    f = rd.get("fundamentals", {})
    u = _EDGAR_XBRL.crypto_units(state.ticker)

    # 单币成功(step-1)：EDGAR 一手单位数 × 实时币价
    if isinstance(u.get("count"), (int, float)):
        return _crypto_nav_block(state, f, rd, [
            {"coin": u["coin"], "count": u["count"], "source": u.get("source"), "as_of": u.get("as_of")}])

    # 多币无法归属(step-1) → 懒触发 step-2 原始 iXBRL 逐币解析(仅此时才下 1.5MB)
    if u.get("is_crypto_filer") is True:
        d = _EDGAR_IXBRL.crypto_units_by_coin(state.ticker)
        if d.get("coins"):
            return _crypto_nav_block(state, f, rd, [
                {"coin": c["coin"], "count": c["count"], "source": d.get("source"), "as_of": d.get("as_of")}
                for c in d["coins"]])
        # step-2 也认不出(通用成员/失败) → 数据不足(优先用 step-2 更具体的 reason)
        return {"type": "crypto_treasury", "applicable": False, "reason": d.get("reason") or u.get("reason")}

    # 无 tag / 无 CIK / 网络失败 → 落回经营/疑似判定(同 v1 非加密路径)
    cls = nav_calc.classify_asset_holder(state.ticker, f, None)
    return {"type": cls["type"], "applicable": cls["nav_applicable"], "reason": cls.get("reason")}


def _crypto_nav_block(state, f, rd, hits: list) -> dict:
    """由持仓 hits[{coin,count,source,as_of}] 组装 NAV 块(单币/多币共用)。
    币价走 _CRYPTO.coin_price(yfinance)；多币求和/缺任一输入 → proto.nav 最严口径整块数据不足。
    nav.py 三函数契约不碰——这里只组装喂给它们的 positions。"""
    cls = nav_calc.classify_asset_holder(state.ticker, f, hits)   # 非空 hits → crypto_treasury
    out = {"type": cls["type"], "applicable": cls["nav_applicable"], "reason": cls.get("reason")}
    if not cls["nav_applicable"]:
        return out
    positions, price_recs = [], {}
    for h in hits:
        pr = _CRYPTO.coin_price(h["coin"])
        price_recs[h["coin"]] = pr
        positions.append({"coin": h["coin"], "count": h["count"], "price": (pr or {}).get("price")})
    cv = nav_calc.crypto_holdings_value(positions)               # 多币求和(v1 起就有)
    result = nav_calc.nav_per_share(
        crypto_value=cv.get("value"),
        cash=f.get("cash"), total_debt=f.get("total_debt"),
        shares=rd.get("shares_outstanding"), current_price=rd.get("price"),
    )
    out.update({
        "coin": cls.get("coin"),
        "holdings": [{"coin": h["coin"], "count": h["count"], "source": h.get("source"),
                      "as_of": h.get("as_of"), "cg_current_value_usd": None} for h in hits],
        "coin_prices": price_recs, "crypto_value": cv, "result": result,
        "discount_notes": nav_calc.DISCOUNT_NOTES,
    })
    return out


# ───────────────────────── 0. DATA（入口节点，迁移新增） ─────────────────────────
def data_stage(state: ResearchState) -> dict:
    """
    取数 + 数据分级入口节点。经 DataAdapter 取标准化 raw_data（不直接调 yfinance），
    返回对 state 的更新(raw_data + tier)，签名与其它 stage 一致。
    """
    raw = _DEFAULT_ADAPTER.fetch(state.ticker)
    tier = DataTier(raw.get("tier", "public"))
    return {"raw_data": raw, "tier": tier}


def _cite(label, value, source, ts, fn=None) -> Citation:
    return Citation(label=label, value=str(value), source=source, timestamp=ts, fn=fn)


def _pct(x) -> str:
    return f"{x*100:.1f}%" if x is not None else "n/a"


def _run_date(state) -> str:
    """运行当天真实日期（取自 raw_data.as_of 的取数时间戳）。
    用 as_of 而非 datetime.now()——as_of 在 fixture 里固定，replay 才确定、不会每天失配。"""
    as_of = (state.raw_data or {}).get("as_of") or ""
    return as_of[:10] if len(as_of) >= 10 else "(运行当天)"


def _date_guard(state) -> str:
    """给会生成时间相关内容的节点的"当前日期感知"铁律。"""
    return (f"\n【今天 = {_run_date(state)}（运行当天真实日期）】所有时间锚点必须在今天之后；"
            f"严禁把已经过去的事件/会议/财报当作未来催化剂；3/6/12 个月窗口一律从今天起算。")


def _ind_num(block) -> bool:
    """指标块是否含真实数字（区别于 {value:None}）。"""
    return isinstance(block.get("value"), (int, float))


def _macro_ind_block(infl: dict, unemp: dict, curve: dict) -> str:
    """把三个 FRED 指标渲染成 prompt 行——有数标真值+所属期，缺则明确'数据不足…不得臆造'。"""
    lines = [
        (f"· 通胀 CPI YoY（截至 {infl['as_of']}）= {_pct(infl['value'])}"
         if _ind_num(infl) else
         f"· 通胀 CPI YoY：数据不足（{infl.get('reason', 'FRED 未返回')}），不得臆造"),
        (f"· 失业率（截至 {unemp['as_of']}）= {_pct(unemp['value'])}"
         if _ind_num(unemp) else
         f"· 失业率：数据不足（{unemp.get('reason', 'FRED 未返回')}），不得臆造"),
        (f"· 收益率曲线 2s10s 价差（截至 {curve['as_of']}）= {_pct(curve['spread'])}"
         f"（{'倒挂⚠️（衰退信号）' if curve['inverted'] else '正常'}）"
         if "spread" in curve else
         f"· 收益率曲线 2s10s：数据不足（{curve.get('reason', 'FRED 未返回')}），不得臆造"),
    ]
    return "\n".join(lines)


# ───────────────────────── 1. MACRO ─────────────────────────
def macro_stage(state: ResearchState) -> dict:
    rd = state.raw_data
    rf_info = rd.get("risk_free", {})
    rf = rf_info.get("rate")
    ts = rf_info.get("timestamp", rd.get("as_of"))

    if rf is None:
        rf = 0.043  # fallback，明确标注
        rf_info = {"source": "fallback assumption (^TNX 不可用)", "timestamp": ts}

    base_discount_rate = rf + EQUITY_RISK_PREMIUM  # 市场基准 β=1，valuation 会用 β 调整

    # FRED 三指标(确定性取值/自算)：喂给 LLM 解读，绝不让 LLM 生成这些数字。缺则数据不足。
    infl = _FRED.inflation()
    unemp = _FRED.unemployment()
    curve = _FRED.yield_curve()
    indicators = {"inflation": infl, "unemployment": unemp, "yield_curve": curve}

    schema = {
        "type": "object",
        "properties": {
            "regime": {"type": "string", "description": "当前宏观周期象限一句话判断"},
            "rate_path": {"type": "string", "description": "利率路径(降/平/升)及依据"},
            "liquidity": {"type": "string", "description": "流动性环境"},
            "expectation_gap": {"type": "string", "description": "市场共识 vs 现实的预期差"},
            "marginal_change": {"type": "string", "description": "相比上期/共识，边际变好还是变坏"},
        },
        "required": ["regime", "rate_path", "liquidity", "expectation_gap", "marginal_change"],
    }
    system = (
        "你是宏观策略师。只解读，不编造数字——所有利率/通胀/失业/收益率数字以给定值为准；"
        "标注'数据不足'的指标一律不得臆造具体数值。收益率曲线倒挂通常预示衰退风险，请据此判断。"
        "必须回答边际变化(相比上期变好/变坏)和预期差，不要罗列现状。"
        + _date_guard(state)
    )
    user = (
        f"今天是 {_run_date(state)}。当前 10Y 美债收益率 = {_pct(rf)}(来源 {rf_info.get('source')})。"
        f"假设股权风险溢价 = {_pct(EQUITY_RISK_PREMIUM)}，则市场基准折现率(β=1) = {_pct(base_discount_rate)}。\n"
        f"【FRED 宏观指标（真实取值，数据所属期已标注）】\n{_macro_ind_block(infl, unemp, curve)}\n"
        f"请结合上述指标判断当前(截至今天)的宏观环境，给出 regime / rate_path / liquidity / expectation_gap / marginal_change；"
        f"regime/rate_path 要体现通胀与就业冷热，liquidity/expectation_gap 可参考收益率曲线；"
        f"涉及 Fed 会议/政策窗口时以今天为基准，不要引用已过去的会议当作前瞻。"
    )
    out = llm.call_structured(llm.SONNET, _guard(state, system), user, schema)

    view = MacroView(
        regime=out["regime"],
        risk_free_rate=rf,
        equity_risk_premium=EQUITY_RISK_PREMIUM,
        base_discount_rate=base_discount_rate,
        rate_path=out["rate_path"],
        liquidity=out["liquidity"],
        expectation_gap=out["expectation_gap"],
        marginal_change=out["marginal_change"],
        indicators=indicators,           # FRED 三指标：数字全来自 FRED，view 只存不由 LLM 生成
    )
    # 收益率曲线 citation 值：有数则"价差（倒挂/正常）"，缺则"数据不足"
    curve_val = (f"{_pct(curve['spread'])}（{'倒挂' if curve['inverted'] else '正常'}）"
                 if "spread" in curve else "数据不足")
    cites = [
        _cite("10Y Treasury yield", _pct(rf), rf_info.get("source"), ts),
        _cite("Equity risk premium (assumption)", _pct(EQUITY_RISK_PREMIUM), "analyst assumption", ts),
        _cite("Base discount rate (β=1)", _pct(base_discount_rate), "tools: rf+ERP", ts),
        _cite("CPI 通胀 (YoY)",
              _pct(infl["value"]) if _ind_num(infl) else "数据不足",
              infl.get("source", "FRED CPIAUCSL") if _ind_num(infl) else f"FRED（{infl.get('reason', '未返回')}）",
              infl.get("as_of", ts)),
        _cite("失业率",
              _pct(unemp["value"]) if _ind_num(unemp) else "数据不足",
              unemp.get("source", "FRED UNRATE") if _ind_num(unemp) else f"FRED（{unemp.get('reason', '未返回')}）",
              unemp.get("as_of", ts)),
        _cite("收益率曲线 2s10s", curve_val,
              curve.get("source", "FRED DGS2/DGS10") if "spread" in curve else f"FRED（{curve.get('reason', '未返回')}）",
              curve.get("as_of", ts)),
    ]
    return {"macro_view": view, "citations": cites}


# ───────────────────────── 2. INDUSTRY ─────────────────────────
def industry_stage(state: ResearchState) -> dict:
    rd = state.raw_data
    sector = rd.get("sector") or "Unknown"
    industry = rd.get("industry") or "Unknown"

    schema = {
        "type": "object",
        "properties": {
            "tam_ceiling": {"type": "string", "description": "该行业 TAM 天花板的显式估算(标明是估算)"},
            "tam_growth": {"type": "string", "description": "TAM 增速判断"},
            "structure": {"type": "string", "description": "竞争格局：集中度/五力"},
            "cycle_position": {"type": "string", "description": "景气周期位置"},
            "valuation_percentile": {"type": "string", "description": "行业估值在历史中的分位判断"},
            "expectation_gap": {"type": "string"},
            "marginal_change": {"type": "string", "description": "相比共识边际变好/变坏"},
        },
        "required": ["tam_ceiling", "tam_growth", "structure", "cycle_position",
                     "valuation_percentile", "expectation_gap", "marginal_change"],
    }
    system = (
        "你是行业分析师。免费数据源拿不到精确 TAM，你给的 TAM 必须显式标为'估算/数量级'，"
        "不要伪装成硬数据。必须回答边际变化和预期差。"
    )
    user = (
        f"行业分类(来自 yfinance)：sector={sector}, industry={industry}。\n"
        f"请就这个'行业'本身(不是某家公司)给出 TAM 天花板估算、增速、竞争格局、景气位置、"
        f"行业估值分位、expectation_gap、marginal_change。"
    )
    out = llm.call_structured(llm.SONNET, _guard(state, system), user, schema)

    view = IndustryView(
        sector=sector, industry=industry,
        tam_ceiling=out["tam_ceiling"], tam_is_estimate=True,
        tam_growth=out["tam_growth"], structure=out["structure"],
        cycle_position=out["cycle_position"],
        valuation_percentile=out["valuation_percentile"],
        expectation_gap=out["expectation_gap"], marginal_change=out["marginal_change"],
    )
    cites = [
        _cite("Sector / Industry", f"{sector} / {industry}", "yfinance info", rd.get("as_of")),
        _cite("Industry TAM ceiling", "估算", "LLM estimate (no free hard source)", rd.get("as_of")),
    ]
    return {"industry_view": view, "citations": cites}


# ───────────────────────── 3. COMPANY ─────────────────────────
def company_stage(state: ResearchState) -> dict:
    rd = state.raw_data
    iv = state.industry_view
    f = rd.get("fundamentals", {})
    rev, rev_prior = f.get("revenue"), f.get("revenue_prior")
    rev_growth = (rev / rev_prior - 1) if (rev and rev_prior) else None

    schema = {
        "type": "object",
        "properties": {
            "business_model": {"type": "string"},
            "revenue_structure": {"type": "string"},
            "moat": {"type": "string", "description": "护城河类型与强度(成本/网络/品牌/转换成本)"},
            "moat_trend": {"type": "string", "description": "护城河边际变化：变宽还是变窄"},
            "growth_ceiling_check": {
                "type": "string",
                "description": "显式对照上游行业 TAM 天花板，判断公司成长空间是否已逼近天花板",
            },
            "expectation_gap": {"type": "string"},
            "marginal_change": {"type": "string", "description": "相比上期，公司基本面边际变好/变坏"},
        },
        "required": ["business_model", "revenue_structure", "moat", "moat_trend",
                     "growth_ceiling_check", "expectation_gap", "marginal_change"],
    }
    system = (
        "你是公司基本面分析师。成长性判断必须受给定行业 TAM 天花板约束——"
        "不能给出突破行业天花板的成长结论。必须回答护城河的边际变化和公司层面的边际变化。只解读，不编造财务数字。"
    )
    user = (
        f"公司：{rd.get('long_name')}（{state.ticker}）。\n"
        f"业务概述：{rd.get('business_summary')}\n"
        f"最近年度营收 = {rev}，上一年度营收 = {rev_prior}，营收同比 = {_pct(rev_growth)}。\n"
        f"【上游行业约束】TAM 天花板 = {iv.tam_ceiling}；行业增速 = {iv.tam_growth}；"
        f"竞争格局 = {iv.structure}。\n"
        f"请输出 business_model / revenue_structure / moat / moat_trend / "
        f"growth_ceiling_check(必须显式引用上面的 TAM 天花板) / expectation_gap / marginal_change。"
    )
    out = llm.call_structured(llm.SONNET, _guard(state, system), user, schema)

    view = CompanyView(
        business_model=out["business_model"], revenue_structure=out["revenue_structure"],
        moat=out["moat"], moat_trend=out["moat_trend"],
        growth_ceiling_check=out["growth_ceiling_check"],
        expectation_gap=out["expectation_gap"], marginal_change=out["marginal_change"],
    )
    cites = [_cite("Revenue YoY", _pct(rev_growth), "yfinance income_stmt", rd.get("as_of"),
                   fn="proto.stages.company_stage")]
    return {"company_view": view, "citations": cites}


# ───────────────────────── 4. FINANCIAL ─────────────────────────
def financial_stage(state: ResearchState) -> dict:
    rd = state.raw_data
    f = rd.get("fundamentals", {})
    ts = rd.get("as_of")
    cites: list[Citation] = []
    anomaly_flags: list[str] = []

    # —— PRE_IPO/数据稀疏：财报缺失就老实输出"数据不足"，绝不调 LLM 编财务数字 ——
    if _preipo(state) or f.get("revenue") is None or f.get("net_income") is None:
        # 质量卡片照样算：缺字段的项各自标"数据不足"，不连坐、不伪造(纯函数，零 LLM)
        q = quality_metrics.company_quality(f, net_debt=rd.get("net_debt"))
        view = FinancialView(
            dupont={}, margins={}, fcf={}, quality=q,
            growth_quality="数据不足（PRE_IPO/数据稀疏，无财报，不估算）",
            anomaly_flags=[], marginal_change="数据不足",
            interpretation="该标的关键财报字段缺失（revenue/net_income 等为 None），无法计算任何财务比率；"
                            "缺失项一律标 None，绝不伪造。",
            citations=[],
        )
        return {"financial_view": view}

    # —— 全部走 tools/ 纯函数，LLM 不算账 ——
    dup = {}
    if all(f.get(k) is not None for k in ("net_income", "revenue", "total_assets", "shareholders_equity")):
        dup = dupont.dupont_roe(f["net_income"], f["revenue"], f["total_assets"], f["shareholders_equity"])
        cites.append(_cite("ROE (DuPont)", _pct(dup["roe"]), "tools.dupont", ts, fn="tools.dupont.dupont_roe"))

    marg, marg_trend = {}, {}
    if all(f.get(k) is not None for k in ("gross_profit", "operating_income", "net_income", "revenue")):
        marg = ratios.margins(f["gross_profit"], f["operating_income"], f["net_income"], f["revenue"])
        cites.append(_cite("Net margin", _pct(marg["net_margin"]), "tools.ratios", ts, fn="tools.ratios.margins"))
        # 边际：用上一年净利率对比 (原则 2)
        if f.get("net_income_prior") and f.get("revenue_prior"):
            prior_nm = f["net_income_prior"] / f["revenue_prior"]
            marg_trend = ratios.margin_trend(marg, {"net_margin": prior_nm})

    fcf = {}
    if f.get("operating_cash_flow") is not None and f.get("capex") is not None:
        fcf = ratios.free_cash_flow(f["operating_cash_flow"], f["capex"])
        cites.append(_cite("Free cash flow", f"{fcf['fcf']:,.0f}", "tools.ratios", ts, fn="tools.ratios.free_cash_flow"))

    gq = {}
    if f.get("operating_cash_flow") is not None and f.get("net_income") is not None:
        gq = ratios.growth_quality(f["operating_cash_flow"], f["net_income"])
        cites.append(_cite("OCF/NI (growth quality)", f"{gq.get('ocf_to_ni')}", "tools.ratios", ts,
                           fn="tools.ratios.growth_quality"))
        if gq.get("ocf_to_ni") is not None and gq["ocf_to_ni"] < 1.0:
            anomaly_flags.append(gq["flag"])

    # OCF 边际变化(本期 vs 上期)
    ocf, ocf_prior = f.get("operating_cash_flow"), f.get("operating_cash_flow_prior")
    ocf_delta = (ocf / ocf_prior - 1) if (ocf and ocf_prior) else None

    # —— 公司质量卡片：ROIC/ROE/增速趋势/杠杆，全部 proto.quality 纯函数算，缺字段标"数据不足" ——
    q = quality_metrics.company_quality(f, net_debt=rd.get("net_debt"))
    for label, key, fmt, fn in (
        ("ROIC", "roic", _pct, "proto.quality.roic"),
        ("ROE", "roe", _pct, "proto.quality.roe"),
        ("资产负债率", "debt_to_assets", _pct, "proto.quality.debt_to_assets"),
        ("净负债/EBITDA", "net_debt_to_ebitda", lambda x: f"{x:.2f}x", "proto.quality.net_debt_to_ebitda"),
    ):
        v = q.get(key, {}).get("value")
        if v is not None:
            cites.append(_cite(label, fmt(v), "proto.quality (computed)", ts, fn=fn))

    schema = {
        "type": "object",
        "properties": {
            "growth_quality": {"type": "string", "description": "真增长 vs 烧钱：基于给定 OCF/NI 数字解读"},
            "anomaly_flags": {"type": "array", "items": {"type": "string"}},
            "marginal_change": {"type": "string", "description": "相比上期的边际财务变化(利润率/现金流趋势)"},
            "interpretation": {"type": "string", "description": "对杜邦/利润率/FCF 这组数字的整体解读"},
        },
        "required": ["growth_quality", "anomaly_flags", "marginal_change", "interpretation"],
    }
    system = (
        "你是财务分析师。下面所有数字都已由确定性工具算好，你只解读，绝不重算或心算新数字。"
        "重点回答：增长是真增长还是烧钱换增长，以及相比上期的边际变化。"
    )
    user = (
        f"杜邦 ROE 拆解：{dup}\n利润率：{marg}\n利润率边际(vs 上期)：{marg_trend}\n"
        f"自由现金流：{fcf}\n增长质量(OCF/NI)：{gq}\n"
        f"营收同比：本期 {f.get('revenue')} vs 上期 {f.get('revenue_prior')}；"
        f"净利润：本期 {f.get('net_income')} vs 上期 {f.get('net_income_prior')}；"
        f"经营现金流同比变化 = {_pct(ocf_delta)}(本期 {ocf} vs 上期 {ocf_prior})。\n"
        f"【公司质量指标(均已由确定性工具算好，值为 None 表示数据不足、不要替它编数字)】：{q}\n"
        f"请输出 growth_quality / anomaly_flags / marginal_change / interpretation"
        f"（interpretation 要点评资本效率(ROIC/ROE)、成长趋势是加速还是放缓、以及杠杆/偿债健康，"
        f"但只能引用上面已算好的数字，数据不足的项就说数据不足）。"
    )
    out = llm.call_structured(llm.SONNET, _guard(state, system), user, schema)

    view = FinancialView(
        dupont=dup, margins={**marg, "trend": marg_trend}, fcf=fcf, quality=q,
        growth_quality=out["growth_quality"],
        anomaly_flags=list(anomaly_flags) + list(out.get("anomaly_flags", [])),
        marginal_change=out["marginal_change"],
        interpretation=out["interpretation"],
        citations=cites,
    )
    return {"financial_view": view, "citations": cites}


# 估值引擎参数(两段式)
EXPLICIT_YEARS = 5      # 显式预测期
FADE_YEARS = 5          # 向 GDP 收敛的过渡期
GDP_ANCHOR = 0.03       # 永续增长锚(名义 GDP 中枢)


def _val_inputs(state: ResearchState):
    """从 state 抽取估值需要的硬数据(给主流程和敏感性共用)。"""
    rd = state.raw_data
    f = rd.get("fundamentals", {})
    base_fcf = f.get("free_cash_flow_reported")
    if base_fcf is None and f.get("operating_cash_flow") and f.get("capex"):
        base_fcf = f["operating_cash_flow"] - abs(f["capex"])
    # 修正口径净现金(change 4)：含有价证券；缺失则退回 -net_debt
    net_cash = rd.get("net_cash")
    if net_cash is None:
        net_cash = -(rd.get("net_debt") or 0.0)
    return {
        "base_fcf": base_fcf,
        "shares": rd.get("shares_outstanding"),
        "net_cash": net_cash,
        "buyback_shrink": rd.get("buyback_shrink") or 0.0,
        "price": rd.get("price"),
        "beta": rd.get("beta") or 1.0,
    }


def _normalize_scenarios(raw) -> list:
    """结构化输出健壮性：scenarios 可能是 list[dict] 或 {name: dict}，统一成 list[dict]。"""
    items = []
    if isinstance(raw, dict):
        for name, v in raw.items():
            if isinstance(v, dict):
                items.append({**v, "name": v.get("name", name)})
    elif isinstance(raw, list):
        items = [s for s in raw if isinstance(s, dict) and s.get("name")]
    return items


def _fallback_scenarios(rev_growth) -> list:
    """
    确定性兜底情景(健壮性修复)：当 scenario LLM 调用返空/不全时，按公司近期营收增速
    fade 到 GDP 生成 Bull/Base/Bear。保证 DCF eligible 标的【永远】产出 3 情景、
    dcf_verdict 永远有值——绝不让盈利/正FCF标的因 LLM 抖动静默退化成倍数分支。
    """
    g0 = rev_growth if isinstance(rev_growth, (int, float)) else 0.05
    g0 = max(-0.20, min(0.30, g0))

    def path(g):
        g = max(-0.30, min(0.50, g))
        return [g, g, max(GDP_ANCHOR, g - 0.005), max(GDP_ANCHOR, g - 0.01), max(GDP_ANCHOR, g - 0.015)]

    spread = 0.03
    return [
        {"name": "Bull", "explicit_growth": path(g0 + spread), "terminal_growth": 0.030,
         "rationale": "确定性兜底(scenario LLM 返空)：近期营收增速 + spread，fade 到 GDP"},
        {"name": "Base", "explicit_growth": path(g0), "terminal_growth": 0.028,
         "rationale": "确定性兜底：贴近期营收增速，fade 到 GDP"},
        {"name": "Bear", "explicit_growth": path(g0 - spread), "terminal_growth": 0.025,
         "rationale": "确定性兜底：近期营收增速 − spread，fade 到 GDP"},
    ]


def _ensure_three_scenarios(scen_items, rev_growth) -> list:
    """
    保证恰好返回 {Bull, Base, Bear} 三套：保留 LLM 给的合法情景，缺的用确定性兜底补齐。
    DCF eligible 标的经此函数后情景永不为空。
    """
    by_name = {s["name"]: s for s in scen_items if isinstance(s, dict) and s.get("name") in ("Bull", "Base", "Bear")}
    if len(by_name) < 3:
        fb = {s["name"]: s for s in _fallback_scenarios(rev_growth)}
        for nm in ("Bull", "Base", "Bear"):
            by_name.setdefault(nm, fb[nm])
    return [by_name["Bull"], by_name["Base"], by_name["Bear"]]


# falsifiers 守门(同 _ensure_three_scenarios 标准)：LLM 返空/不足时不静默放过
_FALLBACK_MARK = "⚠️[确定性兜底·基于已算数据，非 LLM 原生·置信存疑]"


def _deterministic_falsifiers(state) -> list:
    """
    确定性兜底证伪条件：只用【已算出的真实数据】构造，绝不编造具体财务数字/事件。
    Y 全部来自 valuation_view 已算值(隐含增长/三情景价/现价)或"数据可得性"这类结构条件。
    """
    vv = state.valuation_view
    fb = []
    if vv:
        if vv.dcf_verdict and vv.mult_verdict:
            fb.append(f"{_FALLBACK_MARK} 若 DCF 镜头({vv.dcf_verdict})与倍数镜头({vv.mult_verdict})的分歧"
                      f"向任一方向收敛，当前结论的核心依据(两镜头分歧)即被证伪，需重定评级与置信。")
        if vv.implied_perpetual_growth is not None:
            fb.append(f"{_FALLBACK_MARK} 若公司长期增速持续低于现价隐含的永续增长 "
                      f"{vv.implied_perpetual_growth*100:.1f}%(回落至名义 GDP ~3% 水平)，"
                      f"则 DCF 的偏贵判定成立，估值向 DCF 情景区间回归。")
        bear = next((s.per_share_value for s in vv.scenarios if s.name == "Bear"), None)
        bull = next((s.per_share_value for s in vv.scenarios if s.name == "Bull"), None)
        if bear is not None and bull is not None and vv.current_price:
            fb.append(f"{_FALLBACK_MARK} 若现价 ${vv.current_price} 跌入 DCF 三情景区间 "
                      f"${bear}–${bull}，则'现价偏离基本面锚'这一预期差消失。")
        if vv.implied_explicit_cagr is not None:
            fb.append(f"{_FALLBACK_MARK} 若未来显式期实际营收/FCF 复合增速持续低于现价隐含的 "
                      f"{vv.implied_explicit_cagr*100:.1f}%，则增长假设被证伪。")
    # 数据可得性类(PRE_IPO/数据不足/vv 缺失时仍能凑足 3 条，且不涉任何编造数字)
    fb += [
        f"{_FALLBACK_MARK} 若关键数据缺口被补齐(SEC 申报/财报披露/真实同业倍数出现)，"
        f"当前因'数据不足/低置信'得出的结论需整体重估。",
        f"{_FALLBACK_MARK} 若该标的的数据分级(PUBLIC/PRE_IPO)发生变化，分析所走的流程分支随之改变，结论需重判。",
        f"{_FALLBACK_MARK} 若后续披露与本次已用数据出现实质矛盾，则本次分析的输入前提被证伪。",
    ]
    return fb


def _ensure_falsifiers(llm_falsifiers, state) -> list:
    """
    保证 ≥3 条 falsifiers：LLM 给够就用 LLM 的；不足则用确定性兜底补齐(显式标注 _FALLBACK_MARK)，
    绝不假装有，也绝不编造具体数字。
    """
    real = [f for f in (llm_falsifiers or [])
            if isinstance(f, str) and f.strip() and "未提供" not in f and "失败" not in f]
    if len(real) >= 3:
        return real
    out = list(real)
    for f in _deterministic_falsifiers(state):
        if len(out) >= 3:
            break
        out.append(f)
    return out


def _resolve_rating(dcf_disabled: bool, dcf_verdict, mult_verdict) -> dict:
    """
    区分两种 None(健壮性修复，放在 stages 层，不碰 tools/rating.py)：
      · dcf_disabled=True → DCF 被方法路由【主动关闭】(走倍数法，合法) → 用倍数评级
      · dcf_disabled=False 但 dcf_verdict=None → DCF 适用但【计算失败/返空】
        → 绝不退化为倍数法 Sell；标 low_confidence Hold 待复核
      · 否则正常两镜头规则
    """
    if dcf_disabled:
        return rating.decide_rating(None, mult_verdict, dcf_disabled=True)
    if dcf_verdict is None:
        return {"rating": "Hold", "confidence": "low",
                "basis": "DCF 适用但情景计算失败/返空，已标低置信待复核，未退化为倍数法"}
    return rating.decide_rating(dcf_verdict, mult_verdict, dcf_disabled=False)


def _scenario_values(inp, scenarios_assump, discount_rate):
    """给定折现率，把三套假设算成每股价值(纯 tools，无 LLM)。供敏感性复用。"""
    out = {}
    for name, a in scenarios_assump.items():
        tg = min(a["terminal_growth"], discount_rate - 0.005)
        res = dcf.dcf_two_stage_per_share(
            inp["base_fcf"], inp["shares"], inp["net_cash"],
            a["explicit_growth"], FADE_YEARS, tg, discount_rate, inp["buyback_shrink"],
        )
        out[name] = round(res["per_share_value"], 2)
    return out


def _current_multiples(price, net_income, revenue, shares, net_cash):
    """当前 P/E 与 EV/Sales(确定性)。net_income<=0 时 P/E 无意义，跳过。"""
    out, eps = {}, None
    if net_income is not None and shares:
        eps = net_income / shares
        if eps > 0:
            out["pe"] = round(price / eps, 1)
    if revenue and shares:
        ev = price * shares - net_cash       # net_cash 正 → 降低 EV
        out["ev_sales"] = round(ev / revenue, 2)
    return out, eps


_LLM_MULT_SCHEMA = {
    "type": "object",
    "properties": {
        "fair_pe_low": {"type": "number", "description": "同业/历史合理 P/E 下界；未盈利给0"},
        "fair_pe_high": {"type": "number"},
        "fair_ev_sales_low": {"type": "number", "description": "同业/历史合理 EV/Sales 下界"},
        "fair_ev_sales_high": {"type": "number"},
        "note": {"type": "string", "description": "同业基准与依据(标明是估算)"},
    },
    "required": ["fair_pe_low", "fair_pe_high", "fair_ev_sales_low", "fair_ev_sales_high", "note"],
}
_LLM_MULT_SYSTEM = (
    "你是相对估值分析师。免费源拿不到精确同业倍数，你给的合理倍数带必须显式标为'估算'，"
    "锚定该行业/该公司历史正常区间。未盈利公司 P/E 给 0(走 EV/Sales)。"
)


def _fair_multiples_lens(state, inp, net_income, revenue, eps):
    """
    倍数交叉镜头(#2，三方交叉，step4)：
      · Finnhub peer P/E(主，size-matched，给 megacap 定价最贴切)
      · Damodaran 行业 EV/Sales(参照；不用其聚合 PE——小盘高PE 会拉高)
      · 两源分歧 → 降置信(复用 #5)
      · 三级降级：Finnhub 空 → Damodaran → 都没有才退 LLM 估算并标 low_confidence
    口径全 TTM。tools/comparables 只读。
    """
    rd, iv = state.raw_data, state.industry_view
    price, shares, net_cash = inp["price"], inp["shares"], inp["net_cash"]
    net_debt = -net_cash
    sector, industry = rd.get("sector"), rd.get("industry")

    def _bv(fm_lo, fm_hi):
        """一组(下/上界)fair 倍数 → 隐含价值带 + verdict（经 tools.comparables，只读）。"""
        lo = comparables.comparables_valuation(eps if (eps and eps > 0) else None, None, revenue, shares, net_debt, fm_lo)
        hi = comparables.comparables_valuation(eps if (eps and eps > 0) else None, None, revenue, shares, net_debt, fm_hi)
        lows = [v for v in lo["implied_values"].values() if v is not None]
        highs = [v for v in hi["implied_values"].values() if v is not None]
        if not (lows or highs):
            return None, [None, None], None
        band = [round(min(lows + highs), 2), round(max(lows + highs), 2)]
        return comparables.price_vs_band(price, tuple(band)), band, round(sum(lows + highs) / len(lows + highs), 2)

    # 1) Finnhub peer P/E（主镜头）
    fh_detail, fv, fb, fmid = None, None, [None, None], None
    fh = _FINNHUB.get_peer_multiples(state.ticker)
    if fh and fh.get("pe_band") and eps and eps > 0:
        pb = fh["pe_band"]
        fv, fb, fmid = _bv({"pe": pb["p25"]}, {"pe": pb["p75"]})
        fh_detail = {"verdict": fv, "pe_band": pb, "peers": fh["peers"], "n_peers": fh["n_peers"],
                     "source": fh["source"], "asof": "live", "band": fb}

    # 2) Damodaran 行业 EV/Sales（参照；±15% 成带）
    dm_detail, dv, db, dmid = None, None, [None, None], None
    dm = _DAMODARAN.get_industry_multiples(sector, industry)
    if dm and dm.get("ev_sales"):
        evs = dm["ev_sales"]
        dv, db, dmid = _bv({"ev_sales": evs * 0.85}, {"ev_sales": evs * 1.15})
        dm_detail = {"verdict": dv, "ev_sales": evs, "industry": dm["damodaran_industry"],
                     "source": dm["source"], "asof": dm["asof"], "band": db}

    # 3) 末级降级：两真源都没有 → LLM 估算（但 PRE_IPO/数据稀疏标的【禁用】——让 LLM 估倍数=变相伪造）
    llm_detail, lv, lb, lmid = None, None, [None, None], None
    if fv is None and dv is None and not _preipo(state):
        u = (f"标的 {state.ticker}：sector={sector} / industry={industry}；"
             f"当前 P/E={rd.get('trailing_pe')}、forward P/E={rd.get('forward_pe')}；"
             f"行业景气={iv.cycle_position}；行业估值分位={iv.valuation_percentile}。\n"
             f"请给该标的合理的 P/E 带与 EV/Sales 带(同业/历史口径，估算)。")
        fm = llm.call_structured(llm.SONNET, _LLM_MULT_SYSTEM, u, _LLM_MULT_SCHEMA)
        lv, lb, lmid = _bv(
            {"pe": fm["fair_pe_low"] if fm["fair_pe_low"] > 0 else None, "ev_sales": fm["fair_ev_sales_low"]},
            {"pe": fm["fair_pe_high"] if fm["fair_pe_high"] > 0 else None, "ev_sales": fm["fair_ev_sales_high"]},
        )
        llm_detail = {"verdict": lv, "fair_multiples": fm, "source": "LLM 估算(无真源)", "band": lb}

    combined = combine_verdicts(fv, dv, lv)
    if combined is None:
        return {"fair_multiples": {}, "current_multiples": None, "band": [None, None], "midpoint": None,
                "mult_verdict": None,
                "multiples_detail": {"source": None, "low_confidence": True, "cross_check": {},
                                     "note": "无任何倍数源可用"}}

    src = combined["source"]
    if src == "finnhub":
        band, mid, fair_used, asof = fb, fmid, {"finnhub_pe_band": fh_detail["pe_band"]}, "live"
    elif src == "damodaran":
        band, mid, fair_used, asof = db, dmid, {"damodaran_ev_sales": dm_detail["ev_sales"]}, dm_detail["asof"]
    else:
        band, mid, fair_used, asof = lb, lmid, llm_detail.get("fair_multiples", {}), "n/a(LLM)"

    detail = {
        "source": src, "low_confidence": combined["low_confidence"], "cross_check": combined["cross_check"],
        "asof": asof, "finnhub": fh_detail, "damodaran": dm_detail, "llm": llm_detail,
    }
    return {"fair_multiples": fair_used, "current_multiples": None, "band": band, "midpoint": mid,
            "mult_verdict": combined["mult_verdict"], "multiples_detail": detail}


# ───────────────────────── 5. VALUATION（多镜头 #1/#2） ─────────────────────────
def valuation_stage(state: ResearchState) -> dict:
    rd = state.raw_data
    mv, fv, cv, iv = state.macro_view, state.financial_view, state.company_view, state.industry_view
    f = rd.get("fundamentals", {})
    ts = rd.get("as_of")
    nav_block = _build_nav(state)   # NAV 独立区块(资产持有型才算)，三条分支共用

    # —— PRE_IPO/数据稀疏：老实"无法估值"，绝不调 LLM 编 DCF/倍数。
    # 用 tier(_preipo)判定，不用 free_cash_flow_reported——后者缺失不代表无 FCF(可由 OCF-capex 算)。——
    if _preipo(state) or f.get("revenue") is None:
        view = ValuationView(
            method="数据不足，无法估值（PRE_IPO/数据稀疏：缺 FCF/营收等关键字段，绝不伪造）",
            discount_rate_used=0.0, beta=rd.get("beta") or 1.0, discount_rate_basis="n/a（数据不足）",
            current_price=rd.get("price") or 0.0, scenarios=[], dcf_disabled=True, low_confidence=True,
            method_reason="PRE_IPO/数据稀疏，禁用 DCF 与 LLM 倍数估算",
            implied_expectations="数据不足，无法反推隐含预期", expectation_gap="数据不足",
            mult_verdict=None,
            multiples_detail={"source": None, "low_confidence": True, "cross_check": {},
                              "note": "PRE_IPO/数据稀疏，无真倍数源且禁用 LLM 估算 → 无倍数判定"},
            nav=nav_block,
            citations=[_cite("Valuation", "数据不足", "PRE_IPO 降级（不伪造）", ts)],
        )
        return {"valuation_view": view}

    inp = _val_inputs(state)
    beta, price, base_fcf, shares = inp["beta"], inp["price"], inp["base_fcf"], inp["shares"]
    net_cash, shrink = inp["net_cash"], inp["buyback_shrink"]
    net_income, revenue = f.get("net_income"), f.get("revenue")

    rf, erp = mv.risk_free_rate, mv.equity_risk_premium
    discount_rate_used = rf + beta * erp
    discount_rate_basis = (
        f"CAPM: rf({_pct(rf)}) + β({beta:.3f})×ERP({_pct(erp)}) = {_pct(discount_rate_used)}；"
        f"对比 macro 市场基准(β=1) {_pct(mv.base_discount_rate)}"
    )
    rev_growth = (f["revenue"] / f["revenue_prior"] - 1) if (f.get("revenue") and f.get("revenue_prior")) else None

    if shares is None or price is None:
        view = ValuationView(
            method="数据不足", discount_rate_used=discount_rate_used, beta=beta,
            discount_rate_basis=discount_rate_basis, current_price=price or 0.0,
            implied_expectations="缺少股数/价格", expectation_gap="n/a", dcf_disabled=True,
            nav=nav_block,
        )
        return {"valuation_view": view}

    # —— #1 方法路由：负/微 FCF 或未盈利 → 关掉/降级 DCF ——
    route = method_router.select_valuation_method(base_fcf, net_income)
    dcf_eligible = route["dcf_eligible"]

    # —— #2 倍数交叉镜头(两条分支都跑) ——
    current_multiples, eps = _current_multiples(price, net_income, revenue, shares, net_cash)
    lens = _fair_multiples_lens(state, inp, net_income, revenue, eps)
    lens["current_multiples"] = current_multiples
    mult_verdict = lens["mult_verdict"]

    scenarios: list[ValuationScenario] = []
    ipg = iec = None
    dcf_verdict = None
    rule40 = {}
    extra_cites = []

    if not dcf_eligible:
        # —— 多镜头分支：DCF 关闭，走倍数 + Rule-of-40 ——
        fcf_margin = (base_fcf / revenue) if (base_fcf is not None and revenue) else 0.0
        rule40 = comparables.rule_of_40(rev_growth or 0.0, fcf_margin)
        method = "倍数法（EV/Sales + Rule-of-40；DCF 因 FCF<=0 被方法路由关闭）"
        implied_exp = (
            f"DCF 不适用(FCF<=0)。倍数隐含价值带 ${lens['band'][0]}–${lens['band'][1]}，"
            f"现价 ${price} 相对该带为「{mult_verdict}」；Rule-of-40={rule40['score']}({'达标' if rule40['passes'] else '不达标'})。"
        )
        exp_gap = (
            f"未盈利成长股不能用 DCF 定价(会符号反转)。以倍数/Rule-of-40 看，现价相对同业带为「{mult_verdict}」。"
        )
        extra_cites = [
            _cite("Rule of 40", f"{rule40['score']} ({'pass' if rule40['passes'] else 'fail'})",
                  "tools.comparables.rule_of_40", ts, fn="tools.comparables.rule_of_40"),
        ]
    else:
        # —— DCF 分支(两段式)，同时与倍数镜头交叉 ——
        method = f"两段式 per-share DCF（显式{EXPLICIT_YEARS}+fade{FADE_YEARS}+永续；含回购增厚与修正净现金）×倍数交叉"
        schema = {
            "type": "object",
            "properties": {
                "scenarios": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": ["Bull", "Base", "Bear"]},
                            "explicit_growth": {
                                "type": "array", "items": {"type": "number"},
                                "description": f"显式期({EXPLICIT_YEARS}年)逐年 FCF 总量增长率(小数)，长度{EXPLICIT_YEARS}。之后系统会自动 fade 到永续。",
                            },
                            "terminal_growth": {"type": "number", "description": "永续增长率，区间[0.025,0.03]"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["name", "explicit_growth", "terminal_growth", "rationale"],
                    },
                },
            },
            "required": ["scenarios"],
        }
        system = (
            "你是估值分析师。只给三套(Bull/Base/Bear)假设，两段式 DCF 折现由确定性工具执行，你不算账。"
            f"模型结构：显式期{EXPLICIT_YEARS}年用你给的逐年增长，之后{FADE_YEARS}年自动线性 fade 到永续增长，"
            f"再 Gordon 永续；系统已单独建模回购缩股({_pct(shrink)}/年)对每股的增厚，所以你给的是【总量 FCF】增速，不要再叠加缩股。"
            "成长假设必须受行业 TAM 天花板约束，并与财务现状一致。永续增长锚定名义 GDP，区间 2.5%-3%。"
        )
        user = (
            f"标的：{state.ticker}，当前价 = {price}。\n"
            f"基准 FCF(总量) = {base_fcf:,.0f}，修正净现金 = {net_cash:,.0f}(正=净现金)，股数 = {shares:,.0f}，"
            f"年化缩股 = {_pct(shrink)}。\n"
            f"折现率(β调整) = {_pct(discount_rate_used)}。最近营收同比 = {_pct(rev_growth)}。\n"
            f"行业 TAM 天花板(约束) = {iv.tam_ceiling}；行业增速 = {iv.tam_growth}。\n"
            f"公司成长判断 = {cv.growth_ceiling_check}\n财务/增长质量 = {fv.growth_quality}；边际 = {fv.marginal_change}\n"
            f"请给 Bull/Base/Bear 三套 显式期{EXPLICIT_YEARS}年增长 + 永续增长(2.5%-3%)假设。"
        )
        out = llm.call_structured(llm.SONNET, _guard(state, system), user, schema)

        # —— 规整假设 + 用两段式 tools 算每股价值 ——
        # 结构化输出偶尔把 scenarios 返成 dict(按名键)而非 list，统一成 list[dict]；
        # 若返空/不全(LLM 抖动)，确定性兜底补齐——DCF eligible 标的情景永不为空(健壮性修复)
        scen_items = _ensure_three_scenarios(_normalize_scenarios(out.get("scenarios", [])), rev_growth)
        scenarios_assump = {}
        for s in scen_items:
            g = [max(-0.5, min(1.0, float(x))) for x in s.get("explicit_growth", [])][:EXPLICIT_YEARS]
            while len(g) < EXPLICIT_YEARS:
                g.append(g[-1] if g else GDP_ANCHOR)
            tg = max(0.02, min(0.03, float(s.get("terminal_growth", GDP_ANCHOR))))
            scenarios_assump[s["name"]] = {"explicit_growth": g, "terminal_growth": tg}

        vals = _scenario_values(inp, scenarios_assump, discount_rate_used)
        for s in scen_items:
            a = scenarios_assump[s["name"]]
            scenarios.append(ValuationScenario(
                name=s["name"], assumptions=a, per_share_value=vals[s["name"]],
                rationale=s.get("rationale", ""),
            ))

        # —— DCF 镜头判定：现价 vs (Bear, Bull) 区间 ——
        bear_v = next((sc.per_share_value for sc in scenarios if sc.name == "Bear"), None)
        bull_v = next((sc.per_share_value for sc in scenarios if sc.name == "Bull"), None)
        if bear_v is not None and bull_v is not None:
            dcf_verdict = comparables.price_vs_band(price, (min(bear_v, bull_v), max(bear_v, bull_v)))

        # —— change 2：反推隐含永续增长(主) + 隐含显式 CAGR(辅) ——
        base_assump = scenarios_assump.get("Base", {"explicit_growth": [0.05]*EXPLICIT_YEARS, "terminal_growth": GDP_ANCHOR})
        imp_perp = dcf.implied_perpetual_growth(
            target_price=price, base_fcf=base_fcf, shares=shares, net_cash=net_cash,
            explicit_growth=base_assump["explicit_growth"], fade_years=FADE_YEARS,
            discount_rate=discount_rate_used, buyback_shrink=shrink,
        )
        imp_cagr = dcf.implied_explicit_cagr(
            target_price=price, base_fcf=base_fcf, shares=shares, net_cash=net_cash,
            explicit_years=EXPLICIT_YEARS, fade_years=FADE_YEARS, terminal_growth=GDP_ANCHOR,
            discount_rate=discount_rate_used, buyback_shrink=shrink,
        )
        ipg, iec = imp_perp["implied_perpetual_growth"], imp_cagr["implied_explicit_cagr"]

        # —— LLM 解读预期差：DCF 隐含增长 + 倍数镜头是否一致 ——
        schema2 = {
            "type": "object",
            "properties": {
                "implied_expectations": {"type": "string", "description": "大白话：现价隐含了什么增长预期"},
                "expectation_gap": {"type": "string", "description": "DCF隐含 vs 行业/历史/GDP，且与倍数镜头是否一致"},
            },
            "required": ["implied_expectations", "expectation_gap"],
        }
        system2 = (
            "你是估值分析师，只解读给定数字不重算。结论框定为'当前价隐含预期是否合理'，不预测涨跌。"
            "同时点明 DCF 镜头与倍数镜头是否一致——若 DCF 偏空但倍数中性，要明说这可能是 DCF 框架漏算了质量溢价，而非市场错。"
        )
        user2 = (
            f"现价 = {price}。两段式反推：\n"
            f"· 隐含【永续增长率】≈ {_pct(ipg)}(收敛={imp_perp['converged']})——和名义 GDP~3% 比；\n"
            f"· 隐含【显式期{EXPLICIT_YEARS}年 CAGR】≈ {_pct(iec)}(永续固定3%，收敛={imp_cagr['converged']})——和行业/公司历史比。\n"
            f"DCF 镜头判定 = {dcf_verdict}；倍数镜头判定 = {mult_verdict}(倍数隐含带 ${lens['band'][0]}–${lens['band'][1]})。\n"
            f"参照：公司营收同比 = {_pct(rev_growth)}；行业增速 = {iv.tam_growth}。三情景每股价值 = {vals}。\n"
            f"请输出 implied_expectations / expectation_gap。"
        )
        out2 = llm.call_structured(llm.SONNET, system2, user2, schema2)
        implied_exp, exp_gap = out2["implied_expectations"], out2["expectation_gap"]
        extra_cites = [
            _cite("Discount rate (CAPM cost of equity)", _pct(discount_rate_used), "tools: CAPM", ts,
                  fn="proto.stages.valuation_stage"),
            _cite("Base FCF (total)", f"{base_fcf:,.0f}", "yfinance cashflow", ts),
            _cite("Net cash (corrected, incl. securities)", f"{net_cash:,.0f}", "yfinance balance_sheet", ts),
            _cite("Implied perpetual growth @ price", _pct(ipg), "tools.dcf.implied_perpetual_growth", ts,
                  fn="tools.dcf.implied_perpetual_growth"),
            _cite("Implied explicit CAGR @ price", _pct(iec), "tools.dcf.implied_explicit_cagr", ts,
                  fn="tools.dcf.implied_explicit_cagr"),
        ] + [_cite(f"DCF {sc.name} value/share", sc.per_share_value, "tools.dcf.dcf_two_stage_per_share", ts,
                   fn="tools.dcf.dcf_two_stage_per_share") for sc in scenarios]

    # —— 统一构建 ValuationView(两条分支共用) ——
    view = ValuationView(
        method=method, discount_rate_used=discount_rate_used, beta=beta,
        discount_rate_basis=discount_rate_basis, fade_years=FADE_YEARS,
        buyback_shrink=shrink, net_cash=net_cash, scenarios=scenarios, current_price=price,
        implied_perpetual_growth=ipg, implied_explicit_cagr=iec,
        implied_expectations=implied_exp, expectation_gap=exp_gap,
        dcf_disabled=not dcf_eligible, low_confidence=route["low_confidence"], method_reason=route["reason"],
        current_multiples=lens["current_multiples"], fair_multiples=lens["fair_multiples"],
        comparables_band=lens["band"], comparables_midpoint=lens["midpoint"],
        rule_of_40=rule40, dcf_verdict=dcf_verdict, mult_verdict=mult_verdict,
        multiples_detail=lens.get("multiples_detail", {}), nav=nav_block,
        citations=[
            _cite("Buyback shrink rate", _pct(shrink), "yfinance Ordinary Shares Number", ts),
            _cite("Valuation method (router)", route["method"], "tools.method_router", ts,
                  fn="tools.method_router.select_valuation_method"),
            _cite("Multiples implied band", f"${lens['band'][0]}–${lens['band'][1]}", "tools.comparables", ts,
                  fn="tools.comparables.comparables_valuation"),
            _cite("Multiples verdict", str(mult_verdict), "tools.comparables.price_vs_band", ts,
                  fn="tools.comparables.price_vs_band"),
            _cite("Multiples source (3-way)",
                  f"{lens.get('multiples_detail', {}).get('source')} "
                  f"(asof {lens.get('multiples_detail', {}).get('asof')})",
                  "Finnhub peers / Damodaran industry", ts),
        ] + extra_cites,
    )
    return {"valuation_view": view}


# ───────────────────────── 6. CATALYST ─────────────────────────
def catalyst_stage(state: ResearchState) -> dict:
    rd = state.raw_data
    cv, iv = state.company_view, state.industry_view
    earnings = rd.get("earnings_dates", [])

    schema = {
        "type": "object",
        "properties": {
            "catalysts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "horizon": {"type": "string", "enum": ["3m", "6m", "12m"]},
                        "event": {"type": "string"},
                        "direction": {"type": "string", "enum": ["利好", "利空", "双向"]},
                        "note": {"type": "string"},
                    },
                    "required": ["horizon", "event", "direction"],
                },
            },
        },
        "required": ["catalysts"],
    }
    system = ("你是事件分析师。列具体的、可验证的催化剂，避免空泛。已知财报日期请纳入。"
              + _date_guard(state))
    user = (
        f"今天是 {_run_date(state)}。标的：{state.ticker}。已知下一次财报日期：{earnings}。\n"
        f"行业景气：{iv.cycle_position}。公司护城河趋势：{cv.moat_trend}。\n"
        f"请给【从今天起】未来 3/6/12 个月的催化剂清单(财报、产品里程碑、政策窗口、解禁等)，标方向；"
        f"所有时间点必须晚于今天，不得把已过去的事件当未来催化剂。"
    )
    out = llm.call_structured(llm.SONNET, _guard(state, system), user, schema)
    # 健壮性：只接受 dict 形态的 catalyst 项，跳过偶发的非结构化元素
    catalysts = [Catalyst(**c) for c in out.get("catalysts", []) if isinstance(c, dict)]
    return {"catalysts": catalysts}


# ───────────────────────── 7. RISK 红队 (Opus) ─────────────────────────
def risk_stage(state: ResearchState) -> dict:
    mv, iv, cv, fv, vv = (state.macro_view, state.industry_view, state.company_view,
                          state.financial_view, state.valuation_view)
    schema = {
        "type": "object",
        "properties": {
            "bear_thesis": {"type": "string", "description": "强制构建的、有说服力的空头逻辑"},
            "bull_bear_debate": {"type": "string", "description": "一轮多空交锋：多头主张→空头反驳→落点"},
            "risks_by_category": {
                "type": "object",
                "properties": {
                    "技术": {"type": "string"}, "竞争": {"type": "string"}, "监管": {"type": "string"},
                    "财务": {"type": "string"}, "估值": {"type": "string"}, "管理层": {"type": "string"},
                    "宏观": {"type": "string"},
                },
                "required": ["技术", "竞争", "监管", "财务", "估值", "管理层", "宏观"],
            },
            "falsifiers": {
                "type": "array", "items": {"type": "string"}, "minItems": 3,
                "description": "≥3 条：哪些具体可观测事件会证明当前投资逻辑是错的",
            },
        },
        "required": ["bear_thesis", "bull_bear_debate", "risks_by_category", "falsifiers"],
    }
    system = (
        "你是风险红队，职责是证伪而不是吹票。你要读懂并逐一质疑前面所有结论，"
        "强制构建最有力的 bear case，做一轮多空辩论，按 7 类列风险，"
        "并给出至少 3 条明确的 falsifiers(具体、可观测、能证明逻辑错的事件)。"
    )
    user = (
        f"【宏观】{mv.regime} | 边际:{mv.marginal_change} | 预期差:{mv.expectation_gap}\n"
        f"【行业】TAM:{iv.tam_ceiling} | 景气:{iv.cycle_position} | 预期差:{iv.expectation_gap}\n"
        f"【公司】护城河:{cv.moat} | 趋势:{cv.moat_trend} | 天花板:{cv.growth_ceiling_check} | 预期差:{cv.expectation_gap}\n"
        f"【财务】增长质量:{fv.growth_quality} | 边际:{fv.marginal_change} | 异常:{fv.anomaly_flags}\n"
        f"【估值】方法:{vv.method} | 隐含预期:{vv.implied_expectations} | 预期差:{vv.expectation_gap} | "
        f"三情景:{[(s.name, s.per_share_value) for s in vv.scenarios]} | 现价:{vv.current_price}\n"
        f"请质疑以上整条逻辑链，输出 bear_thesis / bull_bear_debate / risks_by_category(7类) / falsifiers(≥3)。"
    )
    out = llm.call_structured(llm.OPUS, _guard(state, system), user, schema, max_tokens=3500)
    # 守门：falsifiers 必须 ≥3，LLM 返空/不足 → 确定性兜底补足(显式标注，绝不假装有/不编数字)
    falsifiers = _ensure_falsifiers(out.get("falsifiers"), state)
    view = RiskView(
        bear_thesis=out["bear_thesis"], bull_bear_debate=out["bull_bear_debate"],
        risks_by_category=out["risks_by_category"], falsifiers=falsifiers,
    )
    return {"risk_view": view}


# ───────────────────────── 8. COMMITTEE (Opus) ─────────────────────────
def committee_stage(state: ResearchState) -> dict:
    vv, rv = state.valuation_view, state.risk_view
    price = vv.current_price
    scen_vals = {s.name: s.per_share_value for s in vv.scenarios}

    # —— PRE_IPO/数据稀疏：确定性产出"数据不足"备忘录，不调 LLM 编评级/目标价/EV ——
    if _preipo(state):
        memo = InvestmentMemo(
            ticker=state.ticker, as_of=state.raw_data.get("as_of"),
            one_liner="数据不足：该标的为 PRE_IPO/数据稀疏（无 SEC 申报且关键财报缺失），"
                      "无法基于基本面给出估值与评级；以下结论一律标注数据不足，绝不伪造缺失数字。",
            implied_expectation="数据不足，无法反推当前价隐含预期。",
            scenario_probabilities={}, expected_value_per_share=None,
            rating="N/A（数据不足）", confidence="low",
            rating_basis="PRE_IPO/数据稀疏：缺关键 fundamentals，禁用 DCF 与 LLM 倍数估算，不伪造评级。",
            valuation_method="insufficient_data",
            target_price_range="数据不足，无法给目标价",
            catalysts=state.catalysts, risk_view=rv,
            position_rules=PositionRules(suggested_weight="数据不足，不建仓", entry="—", add="—", trim="—",
                                         exit="—"),
            citations=state.citations + [
                _cite("Rating", "N/A（数据不足）", "PRE_IPO 降级（不伪造）", state.raw_data.get("as_of")),
            ],
        )
        return {"memo": memo}

    # —— #5：评级由确定性规则决定(多镜头一致性)，LLM 不再自己拍评级 ——
    # _resolve_rating 区分"DCF 路由关闭(倍数法)"与"DCF 计算失败(标低置信，不退化倍数法)"
    rating_result = _resolve_rating(vv.dcf_disabled, vv.dcf_verdict, vv.mult_verdict)
    # 倍数镜头自身两源分歧(Finnhub vs Damodaran) → 进一步下调置信(step4，不无视分歧)
    if vv.multiples_detail.get("low_confidence") and rating_result["confidence"] == "high":
        rating_result = {**rating_result, "confidence": "medium",
                         "basis": rating_result["basis"] + "；倍数两源分歧，置信下调至 medium"}
    # 有节点被熔断降级(Phase9②) → 置信降到 low + 注明，绝不无视降级
    if state.node_failures:
        rating_result = {**rating_result, "confidence": "low",
                         "basis": rating_result["basis"] + f"；⚠️ 有节点降级({len(state.node_failures)}个)，置信降至 low"}

    # LLM 只产出概率/叙事/目标价/仓位，且必须与规则评级一致(不再输出 rating)
    schema = {
        "type": "object",
        "properties": {
            "scenario_probabilities": {
                "type": "object",
                "properties": {"Bull": {"type": "number"}, "Base": {"type": "number"}, "Bear": {"type": "number"}},
                "required": ["Bull", "Base", "Bear"],
                "description": "三情景概率(小数,约和为1)。若无 DCF 情景可给近似主观分布。",
            },
            "one_liner": {"type": "string", "description": "一句话结论，框定为'隐含预期是否合理'，须与给定评级/置信度一致，不预测涨跌"},
            "implied_expectation": {"type": "string"},
            "target_price_range": {"type": "string"},
            "position_rules": {
                "type": "object",
                "properties": {
                    "suggested_weight": {"type": "string"}, "entry": {"type": "string"},
                    "add": {"type": "string"}, "trim": {"type": "string"}, "exit": {"type": "string"},
                },
                "required": ["suggested_weight", "entry", "add", "trim", "exit"],
            },
        },
        "required": ["scenario_probabilities", "one_liner", "implied_expectation",
                     "target_price_range", "position_rules"],
    }
    system = (
        "你是投资委员会主持。评级与置信度已由确定性多镜头规则给定，你不要改写评级，"
        "只产出概率、叙事、目标价区间、仓位规则，且全部必须与给定评级/置信度自洽。"
        "结论框定为'当前价隐含预期是否合理'，绝不预测涨跌。期望估值由系统加权，你不心算。"
        "若评级是低置信 Hold(因 DCF 与倍数分歧)，仓位规则要体现'不确定性大、不重仓任一方向'。"
    )
    user = (
        f"现价 = {price}。\n"
        f"【规则评级】{rating_result['rating']} · 置信度 {rating_result['confidence']} · 依据：{rating_result['basis']}\n"
        f"【镜头】DCF jud:{vv.dcf_verdict} / 倍数 jud:{vv.mult_verdict} / DCF是否关闭:{vv.dcf_disabled}\n"
        f"三情景每股价值 = {scen_vals or '（无 DCF，走倍数）'}；倍数隐含带 = {vv.comparables_band}\n"
        f"估值隐含预期 = {vv.implied_expectations}\n预期差 = {vv.expectation_gap}\n"
        f"空头逻辑 = {rv.bear_thesis}\nfalsifiers = {rv.falsifiers}\n"
        f"请给 scenario_probabilities / one_liner(与评级自洽) / implied_expectation / target_price_range / position_rules。"
    )
    out = llm.call_structured(llm.OPUS, system, user, schema, max_tokens=2500)

    # —— 期望估值：有 DCF 情景则概率加权；无 DCF(倍数法)用倍数带中值(原则 3，不让 LLM 心算) ——
    probs = out["scenario_probabilities"]
    psum = sum(probs.values()) or 1.0
    probs_norm = {k: v / psum for k, v in probs.items()}
    if scen_vals:
        ev = sum(probs_norm.get(name, 0) * scen_vals.get(name, 0) for name in scen_vals)
        ev_basis = "code: Σ prob×scenario_value"
    else:
        ev = vv.comparables_midpoint or 0.0
        probs_norm = {}
        ev_basis = "code: 倍数隐含带中值(DCF 关闭)"

    memo = InvestmentMemo(
        ticker=state.ticker, as_of=state.raw_data.get("as_of"),
        one_liner=out["one_liner"], implied_expectation=out["implied_expectation"],
        scenario_probabilities={k: round(v, 3) for k, v in probs_norm.items()},
        expected_value_per_share=round(ev, 2),
        rating=rating_result["rating"], confidence=rating_result["confidence"],
        rating_basis=rating_result["basis"],
        valuation_method="multiples" if vv.dcf_disabled else "dcf",
        target_price_range=out["target_price_range"],
        catalysts=state.catalysts, risk_view=rv,
        position_rules=PositionRules(**out["position_rules"]),
        citations=state.citations + [
            _cite(f"Rating (rule, {rating_result['confidence']} conf)", rating_result["rating"],
                  "tools.rating.decide_rating", state.raw_data.get("as_of"),
                  fn="tools.rating.decide_rating"),
            _cite("Expected value/share", round(ev, 2), ev_basis, state.raw_data.get("as_of")),
        ],
    )
    return {"memo": memo}


# ───────────────────────── 折现率敏感性(纯 tools，无 LLM) ─────────────────────────
def valuation_sensitivity(state: ResearchState, erps=(0.04, 0.05, 0.055)) -> list:
    """
    在 ERP 三档下重算 DCF 与评级——纯确定性，复用情景假设、委员会概率、固定的倍数镜头。
    评级用多镜头规则(#5)：每档 ERP 重算 DCF 镜头判定，与(ERP 无关的)倍数镜头组合。
    回答"结论对折现率多敏感"，且体现"DCF 偏空但倍数中性→Hold"是否稳健。
    """
    vv = state.valuation_view
    if not vv or not vv.scenarios:
        return []   # DCF 关闭(倍数法)标的没有折现率敏感性
    inp = _val_inputs(state)
    rf, beta = state.macro_view.risk_free_rate, inp["beta"]
    price = vv.current_price
    probs = state.memo.scenario_probabilities if state.memo else {}
    scenarios_assump = {sc.name: sc.assumptions for sc in vv.scenarios}
    mult_verdict = vv.mult_verdict   # 倍数镜头与 ERP 无关，固定

    rows = []
    for erp in erps:
        dr = rf + beta * erp
        vals = _scenario_values(inp, scenarios_assump, dr)
        ev = sum(probs.get(n, 0) * vals.get(n, 0) for n in vals)
        imp_perp = dcf.implied_perpetual_growth(
            target_price=price, base_fcf=inp["base_fcf"], shares=inp["shares"],
            net_cash=inp["net_cash"],
            explicit_growth=scenarios_assump.get("Base", {}).get("explicit_growth", [0.05]*EXPLICIT_YEARS),
            fade_years=FADE_YEARS, discount_rate=dr, buyback_shrink=inp["buyback_shrink"],
        )
        # 每档重算 DCF 镜头判定，再与固定的倍数镜头组合成多镜头评级
        bear_v, bull_v = vals.get("Bear"), vals.get("Bull")
        dcf_verdict = (comparables.price_vs_band(price, (min(bear_v, bull_v), max(bear_v, bull_v)))
                       if (bear_v is not None and bull_v is not None) else None)
        rr = rating.decide_rating(dcf_verdict, mult_verdict, dcf_disabled=False)
        rows.append({
            "erp": erp, "discount_rate": dr,
            "values": vals, "expected_value": round(ev, 2),
            "gap_vs_price": round(ev / price - 1, 4) if price else None,
            "implied_perpetual_growth": imp_perp["implied_perpetual_growth"],
            "dcf_verdict": dcf_verdict, "mult_verdict": mult_verdict,
            "rating": rr["rating"], "confidence": rr["confidence"], "rating_basis": rr["basis"],
        })
    return rows


# ───────────────────────── 市场共识信号(Phase 5 诚实版·非情绪分) ─────────────────────────
def consensus_stage(state: ResearchState) -> dict:
    """
    市场共识信号：分析师评级趋势(buy-side 占比月环比) + 短仓环比。**全确定性、零 LLM。**

    诚实三重保证：① 本节点跑在 committee 之后(graph: …→committee→sensitivity→consensus→END)，
    评级早已产出 → 结构上不可能驱动评级；② 本函数内零 `llm.call_structured`；
    ③ 输出 `market_consensus` 只被 serializer 读，不进任何 LLM 节点 prompt(DoD grep 守)。
    定位：仅作预期差的对照展示(共识看多 vs 镜头判偏贵 = 背离本身是信息)，绝不驱动评级。
    数据缺 → proto.consensus 返回数据不足，绝不编。
    """
    t = state.ticker
    analyst = consensus_calc.analyst_trend(_CONSENSUS.analyst_trends(t))
    short = consensus_calc.short_interest(_CONSENSUS.short_interest(t) or {})
    return {"market_consensus": {"analyst": analyst, "short": short}}
