import pandas as pd

from data_layer import db


def test_init_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"etf_list", "etf_daily", "fetch_state"} <= tables


def test_upsert_etf_list_dedup_on_conflict(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "沪深300ETF", "spot_amount": 1.0}], "t1")
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "沪深300ETF改名", "spot_amount": 2.0}], "t2")
        names = db.get_etf_names(conn)
    assert names == {"510300": "沪深300ETF改名"}


def test_upsert_daily_rows_and_query(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    daily = pd.DataFrame([
        {"trade_date": "2024-01-02", "open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9,
         "volume": 100, "amount": 1000.0, "amplitude": 1.0, "pct_change": 1.0, "change": 0.1, "turnover_rate": 0.5},
        {"trade_date": "2024-01-03", "open": 1.1, "close": 1.2, "high": 1.3, "low": 1.0,
         "volume": 200, "amount": 2000.0, "amplitude": 1.0, "pct_change": 1.0, "change": 0.1, "turnover_rate": 0.5},
    ])
    with db.connect(db_path) as conn:
        n = db.upsert_daily_rows(conn, "510300", daily)
        assert n == 2
        got = db.get_daily_df(conn, "510300")
    assert list(got["trade_date"]) == ["2024-01-02", "2024-01-03"]
    assert got["close"].tolist() == [1.1, 1.2]


def test_upsert_daily_rows_overwrites_same_date(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    row = {"trade_date": "2024-01-02", "open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9,
           "volume": 100, "amount": 1000.0, "amplitude": 1.0, "pct_change": 1.0, "change": 0.1, "turnover_rate": 0.5}
    updated = {**row, "close": 9.9}
    with db.connect(db_path) as conn:
        db.upsert_daily_rows(conn, "510300", pd.DataFrame([row]))
        db.upsert_daily_rows(conn, "510300", pd.DataFrame([updated]))
        got = db.get_daily_df(conn, "510300")
    assert len(got) == 1
    assert got["close"].iloc[0] == 9.9


def test_fetch_state_roundtrip(tmp_path):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        assert db.get_last_trade_date(conn, "510300") is None
        db.set_fetch_state(conn, "510300", "2024-01-03", "2024-01-04T00:00:00", "ok")
        assert db.get_last_trade_date(conn, "510300") == "2024-01-03"
        db.set_fetch_state(conn, "510300", "2024-01-05", "2024-01-06T00:00:00", "ok")
        assert db.get_last_trade_date(conn, "510300") == "2024-01-05"
