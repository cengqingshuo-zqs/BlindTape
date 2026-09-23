import json

import pandas as pd

from training_engine.engine import TrainingSession
from training_engine.export import SCHEMA_VERSION, build_export, save_json
from training_engine.sampling import Sample


def _sample():
    ohlcv = pd.DataFrame({
        "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "open": [10, 20, 15], "high": [10, 20, 15], "low": [10, 20, 15], "close": [10, 20, 15],
        "volume": [100, 100, 100], "amount": [1000, 2000, 1500],
    })
    return Sample(symbol="510300", name="沪深300ETF", start_date="2024-01-02", end_date="2024-01-04", ohlcv=ohlcv)


def test_build_export_revealed_includes_real_identity():
    session = TrainingSession(_sample().ohlcv)
    session.reveal_next()
    session.act("buy", 0.5)
    session.reveal_next()
    session.finish()

    data = build_export(session, _sample(), reveal=True)

    assert data["schema_version"] == SCHEMA_VERSION
    assert data["session_meta"]["symbol"] == "510300"
    assert data["session_meta"]["start_date"] == "2024-01-02"
    assert "trade_date" in data["ohlcv"][0]
    assert len(data["actions"]) == 1
    assert data["actions"][0]["action"] == "buy"
    assert data["system_signals"] is None


def test_build_export_unrevealed_hides_identity_and_dates():
    session = TrainingSession(_sample().ohlcv)
    session.reveal_next()

    data = build_export(session, _sample(), reveal=False)

    assert data["session_meta"]["symbol"] is None
    assert data["session_meta"]["start_date"] is None
    assert "trade_date" not in data["ohlcv"][0]


def test_save_json_writes_readable_file(tmp_path):
    session = TrainingSession(_sample().ohlcv)
    session.reveal_next()
    data = build_export(session, _sample(), reveal=True)

    out = tmp_path / "sub" / "session.json"
    save_json(data, str(out))

    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == SCHEMA_VERSION
