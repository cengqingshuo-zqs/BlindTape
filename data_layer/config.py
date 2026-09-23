"""配置加载：从 config.yaml 读取可调参数，缺省值写在下面的 dataclass 里。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RequestConfig:
    sleep_min_sec: float = 0.5
    sleep_max_sec: float = 1.0
    max_retries: int = 3
    retry_backoff_sec: float = 2.0


@dataclass
class PoolFilterConfig:
    min_years_listed: float = 2.0
    amount_lookback_days: int = 60
    min_avg_amount_yuan: float = 5_000_000
    min_valid_trading_days: int = 480


@dataclass
class SamplingConfig:
    window_trading_days: int = 150
    # 训练窗口之前额外展示的历史背景天数（一进训练就直接看到，不用逐根推进），
    # 只是给个走势背景（比如看MA），不算进可操作的训练窗口里
    context_days: int = 100
    max_start_search_attempts: int = 50
    # 窗口起止日期的日历天跨度不能超过 "理论交易日跨度 * 此倍数"，
    # 用于剔除窗口中间夹了长期停牌的情况（行数是连续的，但日期跳空很大）
    max_calendar_span_ratio: float = 1.8


@dataclass
class TrainingConfig:
    total_capital_yuan: float = 100_000
    default_ma_period: int = 20


@dataclass
class Config:
    db_path: str = "data/blindtape.db"
    output_pool_csv: str = "data/tradable_pool.csv"
    adjust: str = "qfq"
    request: RequestConfig = field(default_factory=RequestConfig)
    pool_filter: PoolFilterConfig = field(default_factory=PoolFilterConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)


def load_config(path: str | Path = "config.yaml") -> Config:
    cfg = Config()
    p = Path(path)
    if not p.exists():
        return cfg

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    for key in ("db_path", "output_pool_csv", "adjust"):
        if key in raw:
            setattr(cfg, key, raw[key])

    for key, value in (raw.get("request") or {}).items():
        setattr(cfg.request, key, value)

    for key, value in (raw.get("pool_filter") or {}).items():
        setattr(cfg.pool_filter, key, value)

    for key, value in (raw.get("sampling") or {}).items():
        setattr(cfg.sampling, key, value)

    for key, value in (raw.get("training") or {}).items():
        setattr(cfg.training, key, value)

    return cfg
