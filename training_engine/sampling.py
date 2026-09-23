"""随机抽样引擎：从可训练标的池里随机选标的+随机起点，抽一个固定长度的训练窗口。"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from data_layer import db
from data_layer.config import SamplingConfig

OHLCV_COLUMNS = ["trade_date", "open", "high", "low", "close", "volume", "amount"]


@dataclass
class Sample:
    symbol: str
    name: str
    start_date: str
    end_date: str
    ohlcv: pd.DataFrame  # 按 trade_date 升序，只含 OHLCV_COLUMNS


def _expected_calendar_span(window_days: int) -> float:
    # A股一年大约242个交易日；用这个比例把"交易日数"换算成"理论应该跨多少日历天"
    return window_days * (365.25 / 242)


def sample_window(
    conn: sqlite3.Connection,
    pool_df: pd.DataFrame,
    cfg: SamplingConfig,
    rng: random.Random | None = None,
) -> Sample:
    """从 pool_df 里 in_pool=True 的标的中随机抽一个 cfg.window_trading_days 长的窗口。

    重抽条件：该标的有效数据不够长；或窗口日历天跨度异常大（中途长期停牌导致数据行连续但日期跳空）。
    """
    rng = rng or random.Random()
    candidates = pool_df.loc[pool_df["in_pool"], "symbol"].tolist()
    if not candidates:
        raise ValueError("标的池为空（in_pool=True 的行数为0），先确认 build-pool 的过滤参数")

    names = db.get_etf_names(conn)
    expected_span = _expected_calendar_span(cfg.window_trading_days)
    max_span = expected_span * cfg.max_calendar_span_ratio

    for _ in range(cfg.max_start_search_attempts):
        # 强制转成str：pool_df如果是从CSV重新读回来的，纯数字的ETF代码列会被pandas
        # 推断成int64，之后无论是查db还是查names字典都会因为类型不一致而出问题
        symbol = str(rng.choice(candidates))
        daily = db.get_daily_df(conn, symbol).dropna(subset=["close"]).reset_index(drop=True)
        if len(daily) < cfg.window_trading_days:
            continue

        start_idx = rng.randint(0, len(daily) - cfg.window_trading_days)
        window = daily.iloc[start_idx: start_idx + cfg.window_trading_days].reset_index(drop=True)

        start_date = datetime.strptime(window["trade_date"].iloc[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(window["trade_date"].iloc[-1], "%Y-%m-%d").date()
        calendar_span = (end_date - start_date).days
        if calendar_span > max_span:
            continue

        return Sample(
            symbol=symbol,
            name=names.get(symbol, ""),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            ohlcv=window[OHLCV_COLUMNS],
        )

    raise RuntimeError(
        f"重试 {cfg.max_start_search_attempts} 次都没找到满足条件的窗口，"
        f"检查标的池是否太小，或 window_trading_days/max_calendar_span_ratio 是否设置过严"
    )
