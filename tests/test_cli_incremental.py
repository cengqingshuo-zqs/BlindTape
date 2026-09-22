import argparse

import pandas as pd

from data_layer import cli, db
from data_layer.config import Config


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "t.db")
    cfg.output_pool_csv = str(tmp_path / "pool.csv")
    cfg.request.sleep_min_sec = 0
    cfg.request.sleep_max_sec = 0
    return cfg


def test_fetch_hist_incremental_starts_after_last_date(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    db.init_db(cfg.db_path)

    seen_start_dates = []

    def fake_fetch_etf_hist(symbol, start_date, adjust):
        seen_start_dates.append(start_date)
        return pd.DataFrame([{
            "trade_date": "2024-01-10", "open": 1.0, "close": 1.0, "high": 1.0, "low": 1.0,
            "volume": 1, "amount": 1.0, "amplitude": 1.0, "pct_change": 0.0, "change": 0.0,
            "turnover_rate": 0.0,
        }])

    monkeypatch.setattr(cli.fetch, "fetch_etf_hist", fake_fetch_etf_hist)

    with db.connect(cfg.db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "x", "spot_amount": 1.0}], "t")
        db.set_fetch_state(conn, "510300", "2024-01-05", "t", "ok")

        args = argparse.Namespace(full=False, symbols=None, limit=None)
        cli.cmd_fetch_hist(conn, cfg, args)

    assert seen_start_dates == ["20240106"]  # last_date + 1 day


def test_fetch_hist_full_ignores_last_date(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    db.init_db(cfg.db_path)

    seen_start_dates = []

    def fake_fetch_etf_hist(symbol, start_date, adjust):
        seen_start_dates.append(start_date)
        return pd.DataFrame(columns=cli.fetch.DAILY_COLUMNS_ORDER)

    monkeypatch.setattr(cli.fetch, "fetch_etf_hist", fake_fetch_etf_hist)

    with db.connect(cfg.db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "x", "spot_amount": 1.0}], "t")
        db.set_fetch_state(conn, "510300", "2024-01-05", "t", "ok")

        args = argparse.Namespace(full=True, symbols=None, limit=None)
        cli.cmd_fetch_hist(conn, cfg, args)

    assert seen_start_dates == ["19700101"]


def test_fetch_hist_records_error_and_keeps_previous_last_date(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    db.init_db(cfg.db_path)

    def failing_fetch(symbol, start_date, adjust):
        raise RuntimeError("network down")

    monkeypatch.setattr(cli.fetch, "fetch_etf_hist", failing_fetch)

    with db.connect(cfg.db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "x", "spot_amount": 1.0}], "t")
        db.set_fetch_state(conn, "510300", "2024-01-05", "t", "ok")

        args = argparse.Namespace(full=False, symbols=None, limit=None)
        cli.cmd_fetch_hist(conn, cfg, args)

        assert db.get_last_trade_date(conn, "510300") == "2024-01-05"
        status = conn.execute("SELECT status FROM fetch_state WHERE symbol='510300'").fetchone()[0]
        assert status == "error"
