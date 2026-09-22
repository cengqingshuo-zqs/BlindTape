import pandas as pd
import pytest

from data_layer import fetch


def test_fetch_etf_list_renames_columns(monkeypatch):
    raw = pd.DataFrame({
        "代码": ["510300", "159915"],
        "名称": ["沪深300ETF", "创业板ETF"],
        "成交额": [123.0, 456.0],
        "其他字段": [1, 2],
    })
    monkeypatch.setattr(fetch.ak, "fund_etf_spot_em", lambda: raw)

    df = fetch.fetch_etf_list()

    assert list(df.columns) == ["symbol", "name", "spot_amount"]
    assert df["symbol"].tolist() == ["510300", "159915"]


def test_fetch_etf_hist_renames_and_formats_date(monkeypatch):
    raw = pd.DataFrame({
        "日期": ["2024-01-02", "2024-01-03"],
        "开盘": [1.0, 1.1],
        "收盘": [1.05, 1.15],
        "最高": [1.1, 1.2],
        "最低": [0.95, 1.0],
        "成交量": [100, 200],
        "成交额": [1000.0, 2000.0],
        "振幅": [1.0, 1.0],
        "涨跌幅": [1.0, 1.0],
        "涨跌额": [0.05, 0.05],
        "换手率": [0.5, 0.5],
    })
    monkeypatch.setattr(fetch.ak, "fund_etf_hist_em", lambda **kwargs: raw)

    df = fetch.fetch_etf_hist("510300")

    assert list(df.columns) == fetch.DAILY_COLUMNS_ORDER
    assert df["trade_date"].tolist() == ["2024-01-02", "2024-01-03"]


def test_fetch_etf_hist_empty_returns_empty_frame_with_columns(monkeypatch):
    monkeypatch.setattr(fetch.ak, "fund_etf_hist_em", lambda **kwargs: pd.DataFrame())

    df = fetch.fetch_etf_hist("999999")

    assert df.empty
    assert list(df.columns) == fetch.DAILY_COLUMNS_ORDER


def test_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    result = fetch.with_retry(flaky, max_retries=5, backoff_sec=0)
    assert result == "ok"
    assert calls["n"] == 3


def test_with_retry_raises_after_exhausting_attempts():
    def always_fails():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        fetch.with_retry(always_fails, max_retries=2, backoff_sec=0)
