import pandas as pd
import pytest

from training_engine.engine import TrainingSession


def _ohlcv(closes):
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [100] * len(closes),
    })


def test_reveal_next_advances_cursor_and_returns_none_at_end():
    session = TrainingSession(_ohlcv([1, 2, 3]))
    assert session.reveal_next() == {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 100}
    assert session.reveal_next()["close"] == 2
    assert session.reveal_next()["close"] == 3
    assert session.reveal_next() is None
    assert session.is_done


def test_act_before_any_reveal_raises():
    session = TrainingSession(_ohlcv([1, 2, 3]))
    with pytest.raises(ValueError):
        session.act("buy", 0.5)


def test_act_rejects_unknown_action():
    session = TrainingSession(_ohlcv([1, 2, 3]))
    session.reveal_next()
    with pytest.raises(ValueError):
        session.act("short", 0.5)


def test_position_clamped_between_0_and_1():
    session = TrainingSession(_ohlcv([1, 2, 3]))
    session.reveal_next()
    session.act("buy", 0.7)
    session.act("add", 0.7)  # 0.7+0.7=1.4 -> 截断到1.0
    assert session.position == 1.0
    session.act("sell", 5.0)  # 远超当前仓位 -> 截断到0
    assert session.position == 0.0


def test_liquidate_zeroes_position():
    session = TrainingSession(_ohlcv([1, 2, 3]))
    session.reveal_next()
    session.act("buy", 0.5)
    session.act("liquidate")
    assert session.position == 0.0
    assert session.actions[-1].action == "liquidate"


def test_equity_curve_flat_when_never_invested():
    session = TrainingSession(_ohlcv([10, 20, 5]))
    session.reveal_next()
    session.reveal_next()
    session.reveal_next()
    equity = session.equity_curve()
    assert equity.tolist() == [1.0, 1.0, 1.0]


def test_equity_curve_full_exposure_from_day0_tracks_price():
    # 第0天买满仓，从第1天起全额吃到涨跌幅
    session = TrainingSession(_ohlcv([10, 20, 10]))
    session.reveal_next()
    session.act("buy", 1.0)
    session.reveal_next()  # day1: 10->20, +100%
    session.reveal_next()  # day2: 20->10, -50%
    equity = session.equity_curve()
    assert equity.iloc[0] == pytest.approx(1.0)
    assert equity.iloc[1] == pytest.approx(2.0)
    assert equity.iloc[2] == pytest.approx(1.0)


def test_action_on_day_i_does_not_affect_day_i_return():
    # day0买入不应该吃到day0本身的涨跌（day0本来就是基准，没有"当天收益"概念），
    # 但更关键的是：day1收盘再加仓，不应该影响day1自己已经走完的那段收益。
    session = TrainingSession(_ohlcv([10, 20, 40]))
    session.reveal_next()  # day0, close=10, 空仓
    session.reveal_next()  # day1, close=20
    session.act("buy", 1.0)  # day1收盘满仓，只对day2生效
    session.reveal_next()  # day2, close=40, 20->40 +100%
    equity = session.equity_curve()
    assert equity.iloc[1] == pytest.approx(1.0)  # day1敞口=0，没吃到day0->day1的涨幅
    assert equity.iloc[2] == pytest.approx(2.0)  # day2敞口=1.0，吃到day1->day2的+100%


def test_stats_max_drawdown_and_time_in_market():
    session = TrainingSession(_ohlcv([10, 20, 10, 10]))
    session.reveal_next()
    session.act("buy", 1.0)
    session.reveal_next()  # +100% -> equity 2.0
    session.reveal_next()  # -50% -> equity 1.0 (回撤到1.0/2.0-1=-50%)
    session.reveal_next()  # flat -> equity 1.0
    stats = session.stats()
    assert stats["max_drawdown"] == pytest.approx(-0.5)
    assert stats["total_return"] == pytest.approx(0.0)
    assert stats["time_in_market_pct"] == pytest.approx(1.0)  # day1/2/3全程持仓
    assert stats["num_actions"] == 1
    assert stats["final_position"] == 1.0


def test_finish_records_finished_at():
    session = TrainingSession(_ohlcv([1, 2]))
    assert session.finished_at is None
    session.finish()
    assert session.finished_at is not None
