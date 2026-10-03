"""
加密国库股数据源(NAV v1) —— 持仓量 + 币价，两个真实输入分别来自独立源。

· 持仓量：CoinGecko 免费 `/companies/public_treasury/{bitcoin|ethereum}`，按 ticker(如 BMNR.US)
  索引，给精确持仓数。第三方聚合(汇编各家披露)，会滞后于最新财报 → 溯源明确标注、不冒充财报直取。
· 币价：yfinance `BTC-USD`/`ETH-USD`(与现有栈一致，零新依赖)。

两张清单按天缓存(一次拉全表覆盖所有 ticker，规避 CoinGecko 免费限频)。
任何网络失败 → 返回 None(上层据此标"数据不足")，绝不崩链、绝不伪造。
LLM 永不参与——持仓数/币价都是这里取的真实数据。
"""
from __future__ import annotations

import json
import datetime as dt
import urllib.request
from pathlib import Path

import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)

# v1 覆盖：BTC/ETH 国库股。币种 → (CoinGecko id, yfinance 行情代码)
_COINS = {"bitcoin": "BTC-USD", "ethereum": "ETH-USD"}
_CG = "https://api.coingecko.com/api/v3/companies/public_treasury"


def _today() -> str:
    return dt.date.today().isoformat()


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "equity-research/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


class CryptoTreasuryAdapter:
    """加密国库持仓 + 币价。失败一律 None，不抛、不编。"""

    def _treasury_list(self, coin: str) -> list | None:
        """取某币种的公开国库清单(按天缓存)。失败返回 None。"""
        cache = CACHE_DIR / f"treasury_{coin}_{_today()}.json"
        if cache.exists():
            try:
                return json.loads(cache.read_text())
            except Exception:  # noqa: BLE001 — 缓存损坏就当没有，重拉
                pass
        try:
            data = _http_json(f"{_CG}/{coin}")
            companies = data.get("companies", [])
            cache.write_text(json.dumps(companies, ensure_ascii=False))
            return companies
        except Exception:  # noqa: BLE001 — 网络/解析失败 → None，上层标数据不足
            return None

    def holdings(self, ticker: str):
        """
        查该 ticker 的加密国库持仓——**遍历所有币种**(一家公司可同时持 BTC+ETH，如 BMNR)，
        返回命中的全部持仓记录 list。未命中任何币 → None(上层判'不适用/数据不足'，绝不编)。
        每条带聚合溯源 + 取数日；CoinGecko 自报市值仅作交叉校验，NAV 仍用持仓数×实时币价。
        """
        sym = f"{ticker.strip().upper()}.US"
        found = []
        for coin in _COINS:
            companies = self._treasury_list(coin)
            if companies is None:
                continue
            for c in companies:
                if (c.get("symbol") or "").upper() == sym:
                    found.append({
                        "coin": coin,
                        "count": c.get("total_holdings"),
                        "cg_current_value_usd": c.get("total_current_value_usd"),
                        "source": "CoinGecko public_treasury(聚合，非财报直取)",
                        "as_of": _today(),
                    })
        return found or None

    def coin_price(self, coin: str) -> dict | None:
        """某币种实时美元价(yfinance)。失败 → None。"""
        symbol = _COINS.get(coin)
        if symbol is None:
            return None
        try:
            h = yf.Ticker(symbol).history(period="1d")
            if h.empty:
                return None
            px = float(h["Close"].dropna().iloc[-1])
            return {"price": px, "source": f"yfinance {symbol}", "as_of": _now_iso()}
        except Exception:  # noqa: BLE001
            return None
