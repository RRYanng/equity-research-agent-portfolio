"""DamodaranAdapter 单测（Phase 1 step2）。纯确定性，零网络（用 bundled 快照/注入 fixture）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proto.data.damodaran import DamodaranAdapter

# 注入 fixture（不依赖磁盘快照内容）测纯逻辑
_FIXTURE = {
    "meta": {"asof": "2026-01", "source": "Damodaran (NYU Stern) US industry averages"},
    "industries": {
        "Computers/Peripherals": {"n_firms": 36, "trailing_pe": 81.13, "ev_sales": 6.63},
        "Software (System & Application)": {"n_firms": 309, "trailing_pe": 79.17, "ev_sales": 11.41},
    },
}


# ── 映射：AAPL/MSFT 必须命中正确 Damodaran 行业 ──
def test_map_aapl_to_computers_peripherals():
    a = DamodaranAdapter(_FIXTURE)
    assert a.map_industry("Technology", "Consumer Electronics") == "Computers/Peripherals"


def test_map_msft_to_software_system_application():
    a = DamodaranAdapter(_FIXTURE)
    assert a.map_industry("Technology", "Software - Infrastructure") == "Software (System & Application)"


def test_unmapped_industry_returns_none_not_guess():
    a = DamodaranAdapter(_FIXTURE)
    assert a.map_industry("Healthcare", "Biotechnology") is None       # 未核对 → 不瞎猜
    assert a.get_industry_multiples("Healthcare", "Biotechnology") is None


# ── 取数：TTM 倍数 + 溯源 ──
def test_get_multiples_aapl_ttm_and_citation():
    a = DamodaranAdapter(_FIXTURE)
    out = a.get_industry_multiples("Technology", "Consumer Electronics")
    assert out["damodaran_industry"] == "Computers/Peripherals"
    assert out["trailing_pe"] == 81.13 and out["ev_sales"] == 6.63
    assert out["basis"] == "TTM"                       # 口径对齐
    assert out["asof"] == "2026-01"                    # 年度快照期入溯源
    assert "Damodaran" in out["source"] and "2026-01" in out["source"]


def test_get_multiples_msft():
    a = DamodaranAdapter(_FIXTURE)
    out = a.get_industry_multiples("Technology", "Software - Infrastructure")
    assert out["damodaran_industry"] == "Software (System & Application)"
    assert out["trailing_pe"] == 79.17 and out["ev_sales"] == 11.41


# Portfolio edition distributes no historical provider observations.
def test_bundled_snapshot_loads_and_asof():
    a = DamodaranAdapter()
    assert a.asof == "not-loaded"
    assert a.get_industry_multiples("Technology", "Consumer Electronics") is None
