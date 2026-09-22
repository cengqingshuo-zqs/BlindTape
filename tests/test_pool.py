from datetime import date, timedelta

import pandas as pd

from data_layer import db, pool
from data_layer.config import PoolFilterConfig


def _make_daily(start: date, n_days: int, amount: float) -> pd.DataFrame:
    rows = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        rows.append({
            "trade_date": d.isoformat(), "open": 1.0, "close": 1.0, "high": 1.0, "low": 1.0,
            "volume": 100, "amount": amount, "amplitude": 1.0, "pct_change": 0.0,
            "change": 0.0, "turnover_rate": 0.5,
        })
    return pd.DataFrame(rows)


def _cfg(**overrides) -> PoolFilterConfig:
    cfg = PoolFilterConfig(
        min_years_listed=2,
        amount_lookback_days=5,
        min_avg_amount_yuan=1_000_000,
        min_valid_trading_days=300,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_qualified_etf_passes_all_filters(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    as_of = date(2026, 1, 1)
    start = as_of - timedelta(days=1000)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "沪深300ETF", "spot_amount": 1.0}], "t")
        db.upsert_daily_rows(conn, "510300", _make_daily(start, 800, amount=5_000_000))
        result = pool.build_pool(conn, _cfg(), as_of=as_of)

    row = result[result["symbol"] == "510300"].iloc[0]
    assert row["in_pool"]
    assert row["reject_reason"] == ""
    assert row["valid_trading_days"] == 800


def test_recently_listed_etf_is_rejected(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    as_of = date(2026, 1, 1)
    start = as_of - timedelta(days=100)  # 上市不满2年
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "159999", "name": "新ETF", "spot_amount": 1.0}], "t")
        db.upsert_daily_rows(conn, "159999", _make_daily(start, 90, amount=5_000_000))
        result = pool.build_pool(conn, _cfg(min_valid_trading_days=10), as_of=as_of)

    row = result[result["symbol"] == "159999"].iloc[0]
    assert not row["in_pool"]
    assert "listed_too_short" in row["reject_reason"]


def test_low_liquidity_etf_is_rejected(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    as_of = date(2026, 1, 1)
    start = as_of - timedelta(days=1000)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "159888", "name": "冷门ETF", "spot_amount": 1.0}], "t")
        db.upsert_daily_rows(conn, "159888", _make_daily(start, 800, amount=100.0))
        result = pool.build_pool(conn, _cfg(), as_of=as_of)

    row = result[result["symbol"] == "159888"].iloc[0]
    assert not row["in_pool"]
    assert "low_liquidity" in row["reject_reason"]


def test_mini_etf_with_sparse_history_is_rejected(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    as_of = date(2026, 1, 1)
    start = as_of - timedelta(days=1000)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "159777", "name": "迷你ETF", "spot_amount": 1.0}], "t")
        db.upsert_daily_rows(conn, "159777", _make_daily(start, 50, amount=5_000_000))
        result = pool.build_pool(conn, _cfg(), as_of=as_of)

    row = result[result["symbol"] == "159777"].iloc[0]
    assert not row["in_pool"]
    assert "not_enough_valid_days" in row["reject_reason"]


def test_symbol_with_no_daily_data_is_marked_no_data(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "999999", "name": "无数据", "spot_amount": 1.0}], "t")
        result = pool.build_pool(conn, _cfg())

    row = result[result["symbol"] == "999999"].iloc[0]
    assert not row["in_pool"]
    assert row["reject_reason"] == "no_data"


def test_recent_avg_amount_uses_lookback_window_only(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    as_of = date(2026, 1, 1)
    start = as_of - timedelta(days=1000)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "沪深300ETF", "spot_amount": 1.0}], "t")
        old = _make_daily(start, 795, amount=100.0)          # 历史很冷门
        recent = _make_daily(as_of - timedelta(days=5), 5, amount=5_000_000)  # 最近5天很活跃
        db.upsert_daily_rows(conn, "510300", pd.concat([old, recent], ignore_index=True))
        result = pool.build_pool(conn, _cfg(amount_lookback_days=5), as_of=as_of)

    row = result[result["symbol"] == "510300"].iloc[0]
    assert row["recent_avg_amount_yuan"] == 5_000_000.0
    assert row["in_pool"]
