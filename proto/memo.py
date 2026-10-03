"""InvestmentMemo -> markdown 渲染。"""
from __future__ import annotations

from .state import ResearchState


def _render_tail(a, state, is_preipo: bool) -> None:
    """共用尾部：催化剂 / 风险 / 仓位 / 逻辑链 / 溯源。PRE_IPO 时守护估值相关行不渲染编造数字。"""
    m, mv, iv, cv, fv, vv, rv = (state.memo, state.macro_view, state.industry_view,
                                 state.company_view, state.financial_view, state.valuation_view,
                                 state.risk_view)
    # 节点熔断降级提示(Phase9②)：有节点失败就在 memo 显式注明，绝不假装完整
    if state.node_failures:
        a(f"\n## ⚠️ 降级节点（circuit breaker）\n")
        a("> 以下节点分析失败、已熔断降级（用确定性降级视图续跑，未拖垮全链）；相关结论置信已降至 low。")
        for nf in state.node_failures:
            a(f"- {nf}")

    a(f"\n## 催化剂时间表\n")
    a("| 时间 | 事件 | 方向 | 备注 |")
    a("|---|---|---|---|")
    for c in m.catalysts:
        a(f"| {c.horizon} | {c.event} | {c.direction} | {c.note} |")

    a(f"\n## 风险与证伪条件\n")
    a(f"**Bear thesis**: {rv.bear_thesis}\n")
    a(f"**多空辩论**: {rv.bull_bear_debate}\n")
    a("**分类风险**:")
    for k, v in rv.risks_by_category.items():
        a(f"- **{k}**: {v}")
    a("\n**Falsifiers（哪些事件会证明逻辑错了）**:")
    for i, fal in enumerate(rv.falsifiers, 1):
        a(f"{i}. {fal}")

    pr = m.position_rules
    a(f"\n## 仓位规则\n")
    a(f"- **建议仓位**: {pr.suggested_weight}")
    a(f"- **建仓**: {pr.entry}")
    a(f"- **加仓**: {pr.add}")
    a(f"- **减仓**: {pr.trim}")
    a(f"- **退出**: {pr.exit}")

    a(f"\n## 逻辑链快照（条件传导）\n")
    a(f"- **宏观**: {mv.regime} | 折现率基准(β=1) {mv.base_discount_rate*100:.1f}% | 边际: {mv.marginal_change}")
    a(f"- **行业**: {iv.sector}/{iv.industry} | TAM(估算): {iv.tam_ceiling} | 景气: {iv.cycle_position}")
    a(f"- **公司**: 护城河 {cv.moat} | 趋势 {cv.moat_trend}")
    a(f"  - ↳ 成长受 TAM 约束: {cv.growth_ceiling_check}")
    a(f"- **财务**: 增长质量 {fv.growth_quality} | 边际 {fv.marginal_change}")
    if fv.dupont:
        a(f"  - 杜邦 ROE={fv.dupont.get('roe',0)*100:.1f}% "
          f"(净利率{fv.dupont.get('net_margin',0)*100:.1f}% × 周转{fv.dupont.get('asset_turnover',0):.2f} "
          f"× 杠杆{fv.dupont.get('equity_multiplier',0):.2f})")
    if is_preipo:
        a(f"- **估值**: 数据不足，未估值（不伪造折现率/估值数字）")
    else:
        a(f"- **估值**: β={vv.beta} → cost of equity {vv.discount_rate_used*100:.1f}%（用标的自己的 β，非市场基准）")

    a(f"\n## 溯源 Citations\n")
    a("| 指标 | 值 | 来源 | 取数函数 | 时间 |")
    a("|---|---|---|---|---|")
    seen = set()
    for c in m.citations:
        key = (c.label, c.value)
        if key in seen:
            continue
        seen.add(key)
        a(f"| {c.label} | {c.value} | {c.source} | {c.fn or '—'} | {c.timestamp} |")
    a(f"\n---\n*本备忘录为研究分析，不构成投资建议。数据源：yfinance / ^TNX / Finnhub / Damodaran；"
      f"TAM 等无免费硬源的字段为显式估算；PRE_IPO 缺失字段标 None 不伪造。*")


def render_memo(state: ResearchState) -> str:
    m = state.memo
    mv, iv, cv, fv, vv, rv = (state.macro_view, state.industry_view, state.company_view,
                              state.financial_view, state.valuation_view, state.risk_view)
    L: list[str] = []
    a = L.append
    is_preipo = bool(state.tier and state.tier.value == "pre_ipo")
    ev_str = "数据不足" if m.expected_value_per_share is None else f"${m.expected_value_per_share}"
    price_str = "数据不足" if not vv.current_price else f"${vv.current_price}"

    a(f"# Investment Memo — {m.ticker}")
    a(f"\n> 研究工具产出，**不构成投资建议**。结论框定为「当前价格隐含预期是否合理」，非涨跌预测。")
    a(f"\n*As of: {m.as_of} · Tier: {state.tier.value if state.tier else 'n/a'} · 现价: {price_str}*")
    if is_preipo:
        a(f"\n> ⚠️ **数据分级：PRE_IPO / 数据稀疏**（{state.raw_data.get('tier_reason','无 SEC 申报且关键财报缺失')}）。"
          f"以下所有缺失字段一律标 None，全程 low_confidence，**绝不伪造任何财务数字**。")

    a(f"\n## 一句话结论\n\n{m.one_liner}")
    a(f"\n**评级**: {m.rating}（置信度 **{m.confidence}**） · **目标价区间**: {m.target_price_range} · "
      f"**估值锚**: {ev_str}")
    a(f"\n*评级依据（多镜头规则）: {m.rating_basis}*")

    if is_preipo:
        # 数据稀疏：单独的"无法估值"块，绝不渲染编造的 DCF/倍数数字
        a(f"\n## 估值（数据不足，无法估值）\n")
        a(f"**{vv.method}**\n")
        a("- DCF：未运行（缺 FCF/营收等关键字段；并已禁用 LLM 倍数估算 → 不伪造）")
        a(f"- 倍数：{(vv.multiples_detail or {}).get('note','数据不足，无真源')}")
        a("- 所有缺失的财务字段一律标 **None**，不估算、不补值。")
        a(f"\n## 当前价格隐含预期\n\n{m.implied_expectation}")
        _render_tail(a, state, is_preipo=True)
        return "\n".join(L)

    # 三方镜头交叉（DCF × Finnhub peer × Damodaran 行业）
    md = vv.multiples_detail or {}
    fh, dm = md.get("finnhub"), md.get("damodaran")
    a(f"\n## 三方镜头交叉（DCF × Finnhub peer × Damodaran 行业）\n")
    a("| 镜头 | 判定 | 来源 / 依据 |")
    a("|---|---|---|")
    dcf_j = vv.dcf_verdict if vv.dcf_verdict else ("关闭" if vv.dcf_disabled else "—")
    a(f"| DCF | {dcf_j} | {('FCF<=0，方法路由关闭' if vv.dcf_disabled else vv.method)} |")
    if fh:
        pb = fh.get("pe_band", {})
        a(f"| Finnhub peer P/E（主） | {fh.get('verdict')} | "
          f"{fh.get('n_peers')} 个 size-matched 同业，P/E 带 {pb.get('p25')}/{pb.get('median')}/{pb.get('p75')}（TTM, live） |")
    if dm:
        a(f"| Damodaran 行业 EV/Sales（参照） | {dm.get('verdict')} | "
          f"{dm.get('industry')}, EV/Sales={dm.get('ev_sales')}（TTM, asof {dm.get('asof')}） |")
    if md.get("source") == "llm_estimate":
        a(f"| 倍数（LLM 估算兜底） | {vv.mult_verdict} | 无真源，三级降级末级，标 low_confidence |")
    a(f"\n*倍数最终判定 = **{vv.mult_verdict}**（主源：{md.get('source')}）*")
    if fh and fh.get("peers"):
        a(f"*Finnhub 同业列表：{', '.join(fh['peers'])}*")
    # 分歧提示
    cc = md.get("cross_check", {})
    if cc.get("agree") is False:
        a(f"\n> ⚠️ **倍数两源分歧**：Finnhub peer 判「{cc.get('finnhub')}」vs Damodaran 行业判「{cc.get('damodaran')}」"
          f"→ 倍数镜头标 low_confidence。")
    if vv.dcf_verdict and vv.mult_verdict and vv.dcf_verdict != vv.mult_verdict:
        a(f"> ⚠️ **DCF 与倍数分歧**：DCF「{vv.dcf_verdict}」vs 倍数「{vv.mult_verdict}」"
          f"→ 评级降置信至 **{m.confidence}**（溢价可能被 DCF 框架漏算，而非市场错）。")

    a(f"\n## 当前价格隐含预期\n\n{m.implied_expectation}")
    a(f"\n{vv.implied_expectations}")
    if vv.implied_perpetual_growth is not None:
        a(f"\n**反推（两段式 DCF）**:")
        a(f"- 隐含**永续增长率** ≈ **{vv.implied_perpetual_growth*100:.1f}%**（显式路径固定为 Base）"
          f" — 对比名义 GDP ~3.0%")
        a(f"- 隐含**显式期 {vv.fade_years}+ 年恒定 CAGR** ≈ **{vv.implied_explicit_cagr*100:.1f}%**（永续固定 3%）"
          f" — 对比行业 CAGR 与公司历史增速")
    a(f"\n**预期差判断**: {vv.expectation_gap}")

    # 估值主体：DCF 分支 → 三情景表；倍数分支 → 倍数带 + Rule-of-40
    if vv.scenarios:
        a(f"\n## Bull / Base / Bear 三情景\n")
        a("| 情景 | 概率 | 每股价值 | 显式期增长 | 永续 | 逻辑 |")
        a("|---|---|---|---|---|---|")
        for s in vv.scenarios:
            p = m.scenario_probabilities.get(s.name, 0)
            g = s.assumptions.get("explicit_growth", [])
            g_str = f"{[round(x*100,1) for x in g]}%"
            tg = round(s.assumptions.get("terminal_growth", 0) * 100, 2)
            a(f"| {s.name} | {p:.0%} | ${s.per_share_value} | {g_str} | {tg}% | {s.rationale} |")
        a(f"\n*估值方法: {vv.method}*")
        a(f"\n*折现率: {vv.discount_rate_basis}*")
        a(f"*净现金(修正口径,含有价证券): ${vv.net_cash/1e9:,.1f}B · 年化回购缩股: {vv.buyback_shrink*100:.1f}%*")
    else:
        a(f"\n## 估值（倍数法 — DCF 已被方法路由关闭）\n")
        a(f"**{vv.method_reason}**\n")
        a(f"- 倍数隐含价值带: **${vv.comparables_band[0]}–${vv.comparables_band[1]}**"
          f"（中值 ${vv.comparables_midpoint}），现价 ${vv.current_price} 相对该带：**{vv.mult_verdict}**")
        if vv.rule_of_40:
            r40 = vv.rule_of_40
            a(f"- Rule-of-40: **{r40.get('score')}**（{'✅ 达标' if r40.get('passes') else '❌ 不达标'}）— {r40.get('detail','')}")
        if vv.current_multiples:
            a(f"- 当前倍数: {vv.current_multiples}")

    # ERP 折现率敏感性（仅 DCF 分支有）
    if state.valuation_sensitivity:
        a(f"\n## 折现率敏感性（ERP 4% / 5% / 5.5%）\n")
        a("> 评级用多镜头规则：每档重算 DCF 判定，与(ERP 无关的)倍数判定组合；两镜头分歧则降置信至 Hold。")
        a("\n| ERP | 折现率 | Bear | Base | Bull | 概率加权EV | EV/现价 | 隐含永续增长 | DCF判定 | 倍数判定 | 评级(置信) |")
        a("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in state.valuation_sensitivity:
            v = r["values"]
            a(f"| {r['erp']*100:.1f}% | {r['discount_rate']*100:.1f}% | "
              f"${v.get('Bear','—')} | ${v.get('Base','—')} | ${v.get('Bull','—')} | "
              f"${r['expected_value']} | {r['gap_vs_price']*100:+.0f}% | "
              f"{r['implied_perpetual_growth']*100:.1f}% | {r['dcf_verdict']} | {r['mult_verdict']} | "
              f"**{r['rating']}**（{r['confidence']}） |")
        a(f"\n*现价 ${vv.current_price}。即使 DCF 随 ERP 变松/变紧，只要倍数镜头中性，多镜头规则就把评级压在 Hold/低置信。*")

    _render_tail(a, state, is_preipo=False)
    return "\n".join(L)
