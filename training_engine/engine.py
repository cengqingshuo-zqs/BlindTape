"""核心训练引擎（无UI）：逐根喂K线、记录操作、算权益曲线/回撤/收益/在场时间。

约定：
- 仓位用 0.0~1.0 表示"虚拟资金里投入这只标的的比例"，不涉及真实下单，也不做杠杆。
- 操作在"当前已揭示的最后一根K线"的收盘价执行（简化模型，不区分次日开盘等更精细的成交假设）。
- 第 i 天的收益率所对应的仓位敞口，是"第 i-1 天收盘后已生效的仓位"——也就是说当天操作
  只影响从下一天起的敞口，不能用今天的操作去吃到今天已经走完的涨跌幅。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

ACTIONS = ("buy", "add", "sell", "liquidate")


@dataclass
class Action:
    day_index: int
    action: str
    price: float
    position_delta: float
    position_after: float


@dataclass
class TrainingSession:
    ohlcv: pd.DataFrame  # 至少含 open/high/low/close/volume，按时间升序，index从0开始连续
    cursor: int = -1  # 已揭示到第几根（-1=还没揭示任何一根）
    position: float = 0.0
    actions: list[Action] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None

    def __post_init__(self):
        self.ohlcv = self.ohlcv.reset_index(drop=True)

    @property
    def total_bars(self) -> int:
        return len(self.ohlcv)

    @property
    def is_done(self) -> bool:
        return self.cursor >= self.total_bars - 1

    def reveal_next(self) -> dict | None:
        """推进一根K线并返回其OHLCV（不含日期/代码）。已经到最后一根则返回None。"""
        if self.is_done:
            return None
        self.cursor += 1
        row = self.ohlcv.iloc[self.cursor]
        return {"open": row["open"], "high": row["high"], "low": row["low"],
                "close": row["close"], "volume": row["volume"]}

    def act(self, action: str, size: float = 0.0) -> Action:
        """在当前已揭示的最后一根K线收盘价执行操作。

        action: "buy"/"add"（加仓，size为正的目标增量比例）、"sell"（减仓，size为正的目标减量比例）、
                "liquidate"（清仓，size忽略）。
        仓位会被截断在 [0, 1] 之间。
        """
        if self.cursor < 0:
            raise ValueError("还没有揭示任何K线，不能操作")
        if action not in ACTIONS:
            raise ValueError(f"未知操作类型: {action!r}，必须是 {ACTIONS} 之一")

        price = float(self.ohlcv.iloc[self.cursor]["close"])

        if action == "liquidate":
            delta = -self.position
        elif action in ("buy", "add"):
            delta = abs(size)
        else:  # sell
            delta = -abs(size)

        new_position = min(1.0, max(0.0, self.position + delta))
        actual_delta = new_position - self.position
        self.position = new_position

        record = Action(self.cursor, action, price, actual_delta, new_position)
        self.actions.append(record)
        return record

    def finish(self) -> None:
        self.finished_at = datetime.now()

    def _exposure_by_day(self) -> np.ndarray:
        """第 i 天(0..cursor)【走完当天涨跌之后】生效的仓位，用于下一天的敞口。"""
        exposure = np.zeros(self.cursor + 1)
        action_at_day: dict[int, float] = {a.day_index: a.position_after for a in self.actions}
        current = 0.0
        for i in range(self.cursor + 1):
            if i in action_at_day:
                current = action_at_day[i]
            exposure[i] = current
        return exposure

    def equity_curve(self) -> pd.Series:
        """从第0天到当前cursor的净值曲线，起点为1.0。"""
        if self.cursor < 0:
            return pd.Series([1.0])

        closes = self.ohlcv["close"].iloc[: self.cursor + 1].to_numpy(dtype=float)
        exposure_after_day = self._exposure_by_day()

        equity = np.ones(self.cursor + 1)
        for i in range(1, self.cursor + 1):
            day_return = closes[i] / closes[i - 1] - 1.0
            exposure_during_day = exposure_after_day[i - 1]  # 昨收后生效的仓位决定今天的敞口
            equity[i] = equity[i - 1] * (1 + exposure_during_day * day_return)
        return pd.Series(equity)

    def stats(self) -> dict:
        equity = self.equity_curve()
        running_max = equity.cummax()
        drawdown = equity / running_max - 1.0

        exposure_after_day = self._exposure_by_day() if self.cursor >= 0 else np.array([])
        # 在场天数占比：从第1天起，敞口>0的天数占比（第0天没有收益可言，不计入分母）
        if self.cursor >= 1:
            in_market_days = int((exposure_after_day[:-1] > 0).sum())
            time_in_market_pct = in_market_days / self.cursor
        else:
            time_in_market_pct = 0.0

        return {
            "total_return": float(equity.iloc[-1] - 1.0),
            "max_drawdown": float(drawdown.min()),
            "time_in_market_pct": time_in_market_pct,
            "num_actions": len(self.actions),
            "final_position": self.position,
        }
