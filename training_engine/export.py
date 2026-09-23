"""训练数据导出结构（草案 v0.1）：把一次训练会话打包成JSON，对应技术方案「训练数据导出结构」一节。

system_signals 先留空占位，等 v1.1系统信号复刻模块 做完后再回填。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .engine import TrainingSession
from .sampling import Sample

SCHEMA_VERSION = "0.1"


def build_export(session: TrainingSession, sample: Sample, reveal: bool = True) -> dict:
    duration_sec = None
    if session.finished_at is not None:
        duration_sec = (session.finished_at - session.started_at).total_seconds()

    ohlcv_cols = ["trade_date", "open", "high", "low", "close", "volume", "amount"] if reveal \
        else ["open", "high", "low", "close", "volume"]
    ohlcv_records = sample.ohlcv[ohlcv_cols].to_dict(orient="records")

    return {
        "schema_version": SCHEMA_VERSION,
        "session_meta": {
            "started_at": session.started_at.isoformat(),
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
            "duration_sec": duration_sec,
            "window_trading_days": len(sample.ohlcv),
            "revealed": reveal,
            "symbol": sample.symbol if reveal else None,
            "name": sample.name if reveal else None,
            "start_date": sample.start_date if reveal else None,
            "end_date": sample.end_date if reveal else None,
        },
        "ohlcv": ohlcv_records,
        "actions": [asdict(a) for a in session.actions],
        "equity_curve": session.equity_curve().tolist(),
        "performance": session.stats(),
        "system_signals": None,  # 占位：v1.1系统信号复刻模块完成后填充进场/加仓/离场点位及对应曲线
    }


def save_json(data: dict, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
