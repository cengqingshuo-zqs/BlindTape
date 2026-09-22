"""可训练标的池：按配置里的过滤规则，从本地历史数据里筛出流动性/历史长度合格的ETF。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pandas as pd

from .config import PoolFilterConfig
from . import db


def _years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


def build_pool(conn: sqlite3.Connection, cfg: PoolFilterConfig, as_of: date | None = None) -> pd.DataFrame:
    """返回每只ETF的统计信息 + 是否入池，不管入池与否都保留一行方便人工核对。"""
    as_of = as_of or date.today()
    names = db.get_etf_names(conn)
    symbols = db.get_all_symbols(conn)

    rows = []
    for symbol in symbols:
        daily = db.get_daily_df(conn, symbol)
        daily = daily.dropna(subset=["close"])
        name = names.get(symbol, "")

        if daily.empty:
            rows.append({
                "symbol": symbol,
                "name": name,
                "start_date": None,
                "end_date": None,
                "valid_trading_days": 0,
                "years_listed": 0.0,
                "recent_avg_amount_yuan": 0.0,
                "in_pool": False,
                "reject_reason": "no_data",
            })
            continue

        start_date = datetime.strptime(daily["trade_date"].iloc[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(daily["trade_date"].iloc[-1], "%Y-%m-%d").date()
        valid_days = len(daily)
        years_listed = _years_between(start_date, as_of)

        recent = daily.tail(cfg.amount_lookback_days)
        recent_avg_amount = float(recent["amount"].mean()) if not recent.empty else 0.0

        reasons = []
        if years_listed < cfg.min_years_listed:
            reasons.append("listed_too_short")
        if valid_days < cfg.min_valid_trading_days:
            reasons.append("not_enough_valid_days")
        if recent_avg_amount < cfg.min_avg_amount_yuan:
            reasons.append("low_liquidity")

        rows.append({
            "symbol": symbol,
            "name": name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "valid_trading_days": valid_days,
            "years_listed": round(years_listed, 2),
            "recent_avg_amount_yuan": round(recent_avg_amount, 2),
            "in_pool": len(reasons) == 0,
            "reject_reason": ",".join(reasons) if reasons else "",
        })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["in_pool", "recent_avg_amount_yuan"], ascending=[False, False])
    return result.reset_index(drop=True)
