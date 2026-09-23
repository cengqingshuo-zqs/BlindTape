import random
from datetime import date, timedelta

import pandas as pd
import pytest

from data_layer import db
from data_layer.config import SamplingConfig
from training_engine import sampling


def _make_daily(start: date, n_days: int) -> pd.DataFrame:
    rows = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        rows.append({
            "trade_date": d.isoformat(), "open": 1.0, "close": 1.0 + i * 0.01, "high": 1.0, "low": 1.0,
            "volume": 100, "amount": 1_000_000.0, "amplitude": 1.0, "pct_change": 0.0,
            "change": 0.0, "turnover_rate": 0.5,
        })
    return pd.DataFrame(rows)


def _seed_symbol(db_path, symbol, name, start, n_days):
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": symbol, "name": name, "spot_amount": 1.0}], "t")
        db.upsert_daily_rows(conn, symbol, _make_daily(start, n_days))


def _pool_df(rows):
    return pd.DataFrame(rows)


def test_sample_window_returns_requested_length(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    _seed_symbol(db_path, "510300", "沪深300ETF", date(2020, 1, 1), 800)
    pool = _pool_df([{"symbol": "510300", "in_pool": True}])
    cfg = SamplingConfig(window_trading_days=150, context_days=100,
                          max_start_search_attempts=10, max_calendar_span_ratio=1.8)

    with db.connect(db_path) as conn:
        sample = sampling.sample_window(conn, pool, cfg, rng=random.Random(42))

    assert sample.symbol == "510300"
    assert len(sample.ohlcv) == 150
    assert len(sample.context_ohlcv) == 100
    assert list(sample.ohlcv.columns) == sampling.OHLCV_COLUMNS
    assert list(sample.context_ohlcv.columns) == sampling.OHLCV_COLUMNS
    # 背景数据必须紧接在训练窗口之前，不能重叠、不能倒序
    assert sample.context_ohlcv["trade_date"].iloc[-1] < sample.ohlcv["trade_date"].iloc[0]


def test_sample_window_context_days_zero_disables_context(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    _seed_symbol(db_path, "510300", "沪深300ETF", date(2020, 1, 1), 200)
    pool = _pool_df([{"symbol": "510300", "in_pool": True}])
    cfg = SamplingConfig(window_trading_days=150, context_days=0,
                          max_start_search_attempts=10, max_calendar_span_ratio=1.8)

    with db.connect(db_path) as conn:
        sample = sampling.sample_window(conn, pool, cfg, rng=random.Random(0))

    assert len(sample.ohlcv) == 150
    assert len(sample.context_ohlcv) == 0


def test_sample_window_skips_symbols_without_enough_data(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    _seed_symbol(db_path, "159999", "太短", date(2024, 1, 1), 50)   # 不够150天
    _seed_symbol(db_path, "510300", "够长", date(2020, 1, 1), 800)
    pool = _pool_df([
        {"symbol": "159999", "in_pool": True},
        {"symbol": "510300", "in_pool": True},
    ])
    cfg = SamplingConfig(window_trading_days=150, max_start_search_attempts=30, max_calendar_span_ratio=1.8)

    with db.connect(db_path) as conn:
        for seed in range(10):
            sample = sampling.sample_window(conn, pool, cfg, rng=random.Random(seed))
            assert sample.symbol == "510300"


def test_sample_window_rejects_in_pool_false_rows(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    _seed_symbol(db_path, "510300", "够长", date(2020, 1, 1), 800)
    pool = _pool_df([{"symbol": "510300", "in_pool": False}])
    cfg = SamplingConfig(window_trading_days=150, max_start_search_attempts=10, max_calendar_span_ratio=1.8)

    with db.connect(db_path) as conn, pytest.raises(ValueError):
        sampling.sample_window(conn, pool, cfg, rng=random.Random(0))


def test_sample_window_rejects_windows_with_long_suspension_gap(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    # 前100天正常，然后跳空1年（长期停牌），再补50天 —— 150行是连续的，但日历跨度异常大
    part1 = _make_daily(date(2020, 1, 1), 100)
    part2 = _make_daily(date(2021, 6, 1), 50)
    combined = pd.concat([part1, part2], ignore_index=True)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "159777", "name": "停牌过的", "spot_amount": 1.0}], "t")
        db.upsert_daily_rows(conn, "159777", combined)

    pool = _pool_df([{"symbol": "159777", "in_pool": True}])
    cfg = SamplingConfig(window_trading_days=150, context_days=0,
                          max_start_search_attempts=5, max_calendar_span_ratio=1.8)

    with db.connect(db_path) as conn, pytest.raises(RuntimeError):
        sampling.sample_window(conn, pool, cfg, rng=random.Random(0))


def test_sample_window_handles_symbol_column_read_back_as_int64(tmp_path):
    # 回归测试：标的池CSV被 pandas 重新读回来时，纯数字代码列会被推断成 int64，
    # 之前 sample_window 会原样把这个 int64 当 symbol 用，导致 db 查询和 names 字典查找不一致
    # （sqlite 靠类型亲和性侥幸查到数据，但 dict.get 因为类型不同必然查不到名字）。
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    _seed_symbol(db_path, "159659", "纳斯达克100ETF招商", date(2020, 1, 1), 800)
    pool = _pool_df([{"symbol": 159659, "in_pool": True}])  # 故意用int模拟CSV读回的情况
    assert pool["symbol"].dtype.kind in ("i", "u")  # 确认真的是整数dtype，不是凑巧

    cfg = SamplingConfig(window_trading_days=150, max_start_search_attempts=10, max_calendar_span_ratio=1.8)
    with db.connect(db_path) as conn:
        sample = sampling.sample_window(conn, pool, cfg, rng=random.Random(0))

    assert sample.symbol == "159659"
    assert sample.name == "纳斯达克100ETF招商"


def test_sample_window_empty_pool_raises(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    cfg = SamplingConfig()
    with db.connect(db_path) as conn, pytest.raises(ValueError):
        sampling.sample_window(conn, pd.DataFrame(columns=["symbol", "in_pool"]), cfg)
