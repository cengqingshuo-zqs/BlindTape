"""对接 akshare 的抓取逻辑：全市场ETF列表、单只ETF历史日线，带重试和限速。"""

from __future__ import annotations

import logging
import random
import time

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# akshare fund_etf_hist_em 返回的中文列名 -> 本地存储用的英文列名
HIST_COLUMN_MAP = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}

DAILY_COLUMNS_ORDER = list(HIST_COLUMN_MAP.values())


def with_retry(func, *args, max_retries: int = 3, backoff_sec: float = 2.0, **kwargs):
    """调用 func(*args, **kwargs)，失败时按 attempt * backoff_sec 退避重试。"""
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # akshare/requests 异常类型不固定，统一兜底重试
            last_exc = exc
            logger.warning("attempt %d/%d failed: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(backoff_sec * attempt)
    assert last_exc is not None
    raise last_exc


def fetch_etf_list() -> pd.DataFrame:
    """拉取全市场ETF列表，返回列 [symbol, name, spot_amount]。"""
    df = ak.fund_etf_spot_em()
    df = df[["代码", "名称", "成交额"]].rename(
        columns={"代码": "symbol", "名称": "name", "成交额": "spot_amount"}
    )
    return df


def fetch_etf_hist(
    symbol: str,
    start_date: str = "19700101",
    end_date: str = "20500101",
    adjust: str = "qfq",
) -> pd.DataFrame:
    """拉取单只ETF历史日线，返回列见 DAILY_COLUMNS_ORDER，trade_date 格式 YYYY-MM-DD。"""
    df = ak.fund_etf_hist_em(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if df.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS_ORDER)

    df = df.rename(columns=HIST_COLUMN_MAP)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    return df[DAILY_COLUMNS_ORDER]


def sleep_between_requests(sleep_min_sec: float, sleep_max_sec: float) -> None:
    time.sleep(random.uniform(sleep_min_sec, sleep_max_sec))
