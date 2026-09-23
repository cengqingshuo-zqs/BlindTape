from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from data_layer import db
from webapp import main as webapp_main


def _make_daily(start: date, n_days: int) -> pd.DataFrame:
    rows = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        close = 10.0 + (i % 5) * 0.1
        rows.append({
            "trade_date": d.isoformat(), "open": close, "close": close, "high": close + 0.05,
            "low": close - 0.05, "volume": 1000, "amount": 10000.0, "amplitude": 1.0,
            "pct_change": 0.0, "change": 0.0, "turnover_rate": 0.5,
        })
    return pd.DataFrame(rows)


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db")
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.upsert_etf_list(conn, [{"symbol": "510300", "name": "沪深300ETF", "spot_amount": 1.0}], "t")
        db.upsert_daily_rows(conn, "510300", _make_daily(date(2020, 1, 1), 800))

    monkeypatch.setattr(webapp_main.CFG, "db_path", db_path)
    monkeypatch.setattr(webapp_main, "POOL_DF", pd.DataFrame([{"symbol": "510300", "in_pool": True}]))
    monkeypatch.setattr(webapp_main, "SESSIONS", {})
    webapp_main.CFG.sampling.window_trading_days = 30
    webapp_main.CFG.sampling.context_days = 20

    return TestClient(webapp_main.app)


def test_create_session_returns_id_and_hides_identity(client):
    resp = client.post("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["total_bars"] == 30
    assert "symbol" not in data
    assert "name" not in data
    assert len(data["context_bars"]) == 20
    assert set(data["context_bars"][0].keys()) == {"open", "high", "low", "close", "volume"}
    assert data["total_capital_yuan"] == 100_000
    assert data["default_ma_periods"] == [5, 20, 0, 0]


def test_reveal_does_not_leak_symbol_or_date(client):
    session_id = client.post("/api/sessions").json()["session_id"]
    resp = client.post(f"/api/sessions/{session_id}/reveal")
    assert resp.status_code == 200
    data = resp.json()
    assert data["done"] is False
    assert set(data["bar"].keys()) == {"open", "high", "low", "close", "volume"}
    assert "trade_date" not in data["bar"]
    assert "symbol" not in str(data)


def test_act_before_reveal_returns_400(client):
    session_id = client.post("/api/sessions").json()["session_id"]
    resp = client.post(f"/api/sessions/{session_id}/act", json={"action": "buy", "size": 0.5})
    assert resp.status_code == 400


def test_answer_rejected_before_finish(client):
    session_id = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{session_id}/reveal")
    resp = client.get(f"/api/sessions/{session_id}/answer")
    assert resp.status_code == 403


def test_export_rejected_before_finish(client):
    session_id = client.post("/api/sessions").json()["session_id"]
    resp = client.get(f"/api/sessions/{session_id}/export")
    assert resp.status_code == 403


def test_full_flow_reveal_act_finish_answer_export(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp_main, "PROJECT_ROOT", tmp_path)

    session_id = client.post("/api/sessions").json()["session_id"]

    for _ in range(30):
        r = client.post(f"/api/sessions/{session_id}/reveal")
        if r.json()["done"]:
            break

    act_resp = client.post(f"/api/sessions/{session_id}/act", json={"action": "buy", "size": 0.4})
    assert act_resp.status_code == 200
    assert act_resp.json()["position_after"] == 0.4

    finish_resp = client.post(f"/api/sessions/{session_id}/finish")
    assert finish_resp.status_code == 200
    assert "total_return" in finish_resp.json()

    answer_resp = client.get(f"/api/sessions/{session_id}/answer")
    assert answer_resp.status_code == 200
    answer = answer_resp.json()
    assert answer["symbol"] == "510300"
    assert answer["name"] == "沪深300ETF"
    assert len(answer["ohlcv"]) == 30
    assert len(answer["context_ohlcv"]) == 20
    assert "trade_date" in answer["context_ohlcv"][0]
    assert len(answer["actions"]) == 1

    export_resp = client.get(f"/api/sessions/{session_id}/export")
    assert export_resp.status_code == 200
    exported = export_resp.json()
    assert exported["session_meta"]["symbol"] == "510300"
    assert (tmp_path / "data" / "sessions" / f"session_{session_id}.json").exists()


def test_unknown_session_returns_404(client):
    resp = client.post("/api/sessions/does-not-exist/reveal")
    assert resp.status_code == 404
