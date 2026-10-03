"""
DamodaranAdapter（Phase 1 step 2）—— 美股行业平均倍数（权威行业基准镜头）。

数据源：Damodaran (NYU Stern) 美股行业 averages。Portfolio edition 不分发原始快照；默认模板为空，需自行获取本地数据。
口径：TTM/trailing（trailing_pe = price / 过去12月EPS；ev_sales = EV / 过去12月营收），
     与 tools/comparables 的 P/E、EV/Sales 口径对齐，绝不混 forward/NTM。

映射：yfinance (sector, industry) → Damodaran 行业名。**先手工核对 AAPL/MSFT 两支**，
     未命中返回 None（降级，绝不瞎猜映射）。

诚实：行业是 aggregate/average，含大量小盘高PE，megacap 个股 PE 常低于行业聚合——
     故 step 3 要配 Finnhub size-matched peer-median 交叉，分歧降置信。
"""
from __future__ import annotations

import json
from pathlib import Path

_SNAPSHOT = Path(__file__).resolve().parent / "damodaran_template.json"


class DamodaranAdapter:
    SOURCE = "Damodaran (NYU Stern) US industry averages"

    # 手工核对的映射（先只 AAPL/MSFT，确认合理后再扩——不一上来自动映射全行业）
    _INDUSTRY_MAP = {
        ("Technology", "Consumer Electronics"): "Computers/Peripherals",          # AAPL
        ("Technology", "Software - Infrastructure"): "Software (System & Application)",  # MSFT
    }

    def __init__(self, data: dict | None = None):
        self._data = data if data is not None else json.loads(_SNAPSHOT.read_text())

    @property
    def asof(self) -> str:
        return self._data["meta"]["asof"]

    def map_industry(self, sector: str | None, industry: str | None) -> str | None:
        """yfinance (sector, industry) → Damodaran 行业名；未核对的返回 None。"""
        return self._INDUSTRY_MAP.get((sector, industry))

    def get_industry_multiples(self, sector: str | None, industry: str | None) -> dict | None:
        """
        返回该标的所属 Damodaran 行业的 TTM 倍数 + 溯源（asof/source）。
        映射未命中或该行业无数据 → None（让上游降级，不伪造）。
        """
        dind = self.map_industry(sector, industry)
        if not dind:
            return None
        row = self._data["industries"].get(dind)
        if not row:
            return None
        return {
            "damodaran_industry": dind,
            "trailing_pe": row.get("trailing_pe"),   # TTM
            "ev_sales": row.get("ev_sales"),         # TTM
            "n_firms": row.get("n_firms"),
            "asof": self.asof,                       # 年度快照期，存进溯源
            "source": f"{self.SOURCE} ({self.asof})",
            "basis": "TTM",
        }

    # —— 年度更新用：从 Damodaran 重新下载并重建快照 JSON（不在测试里跑网络） ——
    def refresh(self, out_path: Path | None = None) -> dict:
        """
        从 Damodaran 三张 HTML 表(pe/ps/vebitda)重建快照。供每年更新一次。
        best-effort：依赖 pandas.read_html，失败时抛错由调用方决定是否沿用旧快照。
        """
        import pandas as pd  # 局部 import，避免常态依赖
        urls = self._data["meta"]["urls"]

        def _by_industry(url, value_col_candidates):
            tables = pd.read_html(url)
            df = max(tables, key=len)  # 取最大的表
            name_col = next(c for c in df.columns if "Industry" in str(c))
            val_col = next(c for c in df.columns
                           if any(k.lower() in str(c).lower() for k in value_col_candidates))
            out = {}
            for _, r in df.iterrows():
                ind = str(r[name_col]).strip()
                try:
                    out[ind] = float(r[val_col])
                except (ValueError, TypeError):
                    out[ind] = None
            return out

        pe = _by_industry(urls["pe"], ["Trailing PE"])
        evs = _by_industry(urls["ev_sales"], ["EV/Sales"])
        industries = {}
        for ind in set(pe) | set(evs):
            industries[ind] = {"trailing_pe": pe.get(ind), "ev_sales": evs.get(ind)}
        rebuilt = {"meta": dict(self._data["meta"]), "industries": industries}
        if out_path:
            out_path.write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2))
        return rebuilt
