"""SQLite 存储层：建表、增删改查。所有写操作都在一个 connect() 上下文里提交。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS etf_list (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spot_amount REAL,
    list_snapshot_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etf_daily (
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume REAL,
    amount REAL,
    amplitude REAL,
    pct_change REAL,
    change REAL,
    turnover_rate REAL,
    PRIMARY KEY (symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_etf_daily_symbol_date ON etf_daily(symbol, trade_date);

CREATE TABLE IF NOT EXISTS fetch_state (
    symbol TEXT PRIMARY KEY,
    last_trade_date TEXT,
    last_fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT
);
"""

DAILY_COLUMNS = [
    "trade_date", "open", "close", "high", "low",
    "volume", "amount", "amplitude", "pct_change", "change", "turnover_rate",
]


@contextmanager
def connect(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_etf_list(conn: sqlite3.Connection, rows: list[dict], snapshot_at: str) -> None:
    conn.executemany(
        """
        INSERT INTO etf_list (symbol, name, spot_amount, list_snapshot_at)
        VALUES (:symbol, :name, :spot_amount, :snapshot_at)
        ON CONFLICT(symbol) DO UPDATE SET
            name = excluded.name,
            spot_amount = excluded.spot_amount,
            list_snapshot_at = excluded.list_snapshot_at
        """,
        [{**r, "snapshot_at": snapshot_at} for r in rows],
    )


def upsert_daily_rows(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    records = [
        {"symbol": symbol, **{c: row[c] for c in DAILY_COLUMNS}}
        for row in df.to_dict(orient="records")
    ]
    conn.executemany(
        """
        INSERT INTO etf_daily
            (symbol, trade_date, open, close, high, low, volume, amount,
             amplitude, pct_change, change, turnover_rate)
        VALUES
            (:symbol, :trade_date, :open, :close, :high, :low, :volume, :amount,
             :amplitude, :pct_change, :change, :turnover_rate)
        ON CONFLICT(symbol, trade_date) DO UPDATE SET
            open = excluded.open,
            close = excluded.close,
            high = excluded.high,
            low = excluded.low,
            volume = excluded.volume,
            amount = excluded.amount,
            amplitude = excluded.amplitude,
            pct_change = excluded.pct_change,
            change = excluded.change,
            turnover_rate = excluded.turnover_rate
        """,
        records,
    )
    return len(records)


def get_last_trade_date(conn: sqlite3.Connection, symbol: str) -> str | None:
    cur = conn.execute("SELECT last_trade_date FROM fetch_state WHERE symbol = ?", (symbol,))
    row = cur.fetchone()
    return row[0] if row else None


def set_fetch_state(
    conn: sqlite3.Connection,
    symbol: str,
    last_trade_date: str | None,
    fetched_at: str,
    status: str,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO fetch_state (symbol, last_trade_date, last_fetched_at, status, error_message)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            last_trade_date = excluded.last_trade_date,
            last_fetched_at = excluded.last_fetched_at,
            status = excluded.status,
            error_message = excluded.error_message
        """,
        (symbol, last_trade_date, fetched_at, status, error_message),
    )


def get_all_symbols(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT symbol FROM etf_list ORDER BY symbol")]


def get_etf_names(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT symbol, name FROM etf_list"))


def get_daily_df(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT * FROM etf_daily WHERE symbol = ? ORDER BY trade_date ASC",
        conn,
        params=(symbol,),
    )
    return df
