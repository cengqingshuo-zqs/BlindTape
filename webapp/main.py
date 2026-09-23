"""BlindTape 训练前端后端（技术方案「开发顺序」第4步的最小可用版本）。

范围：随机抽样 -> 逐根推进 -> 操作 -> 复盘 -> 导出 全链路打通。
不包含：v1.1系统信号复刻叠加（模块4还没做，等做完再往复盘接口里加）、历史训练记录持久化、
部署/Tailscale（那是第5步）。

会话状态存在进程内存里（dict），服务重启就没了——单人自用工具，先不做持久化。

运行方式：
    uvicorn webapp.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from data_layer import db
from data_layer import pool as pool_mod
from data_layer.config import load_config
from training_engine import export as export_mod
from training_engine.engine import TrainingSession
from training_engine.sampling import sample_window

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(str(PROJECT_ROOT / "config.yaml"))


def _load_pool_df() -> pd.DataFrame:
    pool_csv = PROJECT_ROOT / CFG.output_pool_csv
    if pool_csv.exists():
        # dtype强制str：纯数字的ETF代码列不指定的话会被pandas推断成int64（training_engine/sampling.py有同样的注释）
        return pd.read_csv(pool_csv, dtype={"symbol": str})
    with db.connect(str(PROJECT_ROOT / CFG.db_path)) as conn:
        return pool_mod.build_pool(conn, CFG.pool_filter)


POOL_DF = _load_pool_df()


class _SessionEntry:
    __slots__ = ("session", "sample")

    def __init__(self, session: TrainingSession, sample) -> None:
        self.session = session
        self.sample = sample


SESSIONS: dict[str, _SessionEntry] = {}


class ActRequest(BaseModel):
    action: str
    size: float = 0.0


def _get_entry(session_id: str) -> _SessionEntry:
    entry = SESSIONS.get(session_id)
    if entry is None:
        raise HTTPException(404, "训练会话不存在（服务重启过的话，之前的会话都会丢失，重新开一个新的训练）")
    return entry


app = FastAPI(title="BlindTape")


def _bar_records(ohlcv) -> list[dict]:
    """只给OHLCV数值，不带trade_date——盲测阶段不能泄露日期。"""
    cols = ["open", "high", "low", "close", "volume"]
    return ohlcv[cols].to_dict(orient="records")


@app.post("/api/sessions")
def create_session():
    with db.connect(str(PROJECT_ROOT / CFG.db_path)) as conn:
        sample = sample_window(conn, POOL_DF, CFG.sampling)
    session = TrainingSession(sample.ohlcv)
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = _SessionEntry(session, sample)
    return {
        "session_id": session_id,
        "total_bars": session.total_bars,
        "window_trading_days": CFG.sampling.window_trading_days,
        "context_bars": _bar_records(sample.context_ohlcv),
        "total_capital_yuan": CFG.training.total_capital_yuan,
        "default_ma_periods": CFG.training.default_ma_periods,
    }


@app.post("/api/sessions/{session_id}/reveal")
def reveal(session_id: str):
    entry = _get_entry(session_id)
    bar = entry.session.reveal_next()
    return {
        "done": bar is None,
        "bar": bar,
        "day_index": entry.session.cursor,
        "total_bars": entry.session.total_bars,
        "position": entry.session.position,
    }


@app.post("/api/sessions/{session_id}/act")
def act(session_id: str, req: ActRequest):
    entry = _get_entry(session_id)
    try:
        record = entry.session.act(req.action, req.size)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "day_index": record.day_index,
        "action": record.action,
        "price": record.price,
        "position_delta": record.position_delta,
        "position_after": record.position_after,
    }


@app.post("/api/sessions/{session_id}/finish")
def finish(session_id: str):
    entry = _get_entry(session_id)
    entry.session.finish()
    return entry.session.stats()


@app.get("/api/sessions/{session_id}/answer")
def answer(session_id: str):
    entry = _get_entry(session_id)
    if entry.session.finished_at is None:
        raise HTTPException(403, "训练还没结束，不能揭晓")

    return {
        "symbol": entry.sample.symbol,
        "name": entry.sample.name,
        "start_date": entry.sample.start_date,
        "end_date": entry.sample.end_date,
        "context_ohlcv": entry.sample.context_ohlcv.to_dict(orient="records"),
        "ohlcv": entry.sample.ohlcv.to_dict(orient="records"),
        "actions": [
            {
                "day_index": a.day_index,
                "action": a.action,
                "price": a.price,
                "position_delta": a.position_delta,
                "position_after": a.position_after,
            }
            for a in entry.session.actions
        ],
        "equity_curve": entry.session.equity_curve().tolist(),
        "performance": entry.session.stats(),
    }


@app.get("/api/sessions/{session_id}/export")
def export_session(session_id: str):
    entry = _get_entry(session_id)
    if entry.session.finished_at is None:
        raise HTTPException(403, "训练还没结束，不能导出")

    data = export_mod.build_export(entry.session, entry.sample, reveal=True)
    out_path = PROJECT_ROOT / "data" / "sessions" / f"session_{session_id}.json"
    export_mod.save_json(data, str(out_path))
    return data


app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="static")
