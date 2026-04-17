"""
Monte Carlo simulation — shuffles trade order to estimate confidence
intervals for key performance metrics.

By randomising the sequence of trades, we answer: "How likely is this
drawdown / final equity just because of the particular order trades
happened in?"  Wide confidence intervals signal fragile strategies.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class MonteCarloResult:
    """Aggregated Monte Carlo simulation output."""

    num_simulations: int
    initial_balance: float
    final_equity: dict[str, float]
    max_drawdown_pct: dict[str, float]
    sharpe_ratio: dict[str, float]

    def summary(self) -> dict[str, Any]:
        return {
            "num_simulations": self.num_simulations,
            "initial_balance": self.initial_balance,
            "final_equity": self.final_equity,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
        }


class MonteCarloSimulator:
    """Shuffle completed trades and recompute equity curves.

    Usage:
        sim = MonteCarloSimulator(trades, initial_balance=10_000)
        result = sim.run()
        print(result.final_equity)  # {'p5': ..., 'p50': ..., 'p95': ...}
    """

    def __init__(
        self,
        trades: list,
        initial_balance: float = 10_000.0,
        num_simulations: int = 1000,
        seed: int = 42,
    ) -> None:
        self.trades = trades
        self.initial_balance = initial_balance
        self.num_simulations = num_simulations
        self._rng = random.Random(seed)

    def run(self) -> MonteCarloResult:
        if not self.trades:
            empty_pcts = {"p5": 0.0, "p50": 0.0, "p95": 0.0}
            return MonteCarloResult(
                num_simulations=0,
                initial_balance=self.initial_balance,
                final_equity=empty_pcts,
                max_drawdown_pct=empty_pcts,
                sharpe_ratio=empty_pcts,
            )

        net_pnls = [t.net_pnl for t in self.trades]

        final_equities: list[float] = []
        max_drawdowns: list[float] = []
        sharpe_ratios: list[float] = []

        for _ in range(self.num_simulations):
            shuffled = list(net_pnls)
            self._rng.shuffle(shuffled)

            equity_curve = self._build_equity_curve(shuffled)
            final_equities.append(equity_curve[-1])
            max_drawdowns.append(self._max_drawdown(equity_curve))
            sharpe_ratios.append(self._sharpe(equity_curve))

        return MonteCarloResult(
            num_simulations=self.num_simulations,
            initial_balance=self.initial_balance,
            final_equity=_percentiles(final_equities),
            max_drawdown_pct=_percentiles(max_drawdowns),
            sharpe_ratio=_percentiles(sharpe_ratios),
        )

    def _build_equity_curve(self, pnls: list[float]) -> list[float]:
        curve = [self.initial_balance]
        for pnl in pnls:
            curve.append(curve[-1] + pnl)
        return curve

    @staticmethod
    def _max_drawdown(equity_curve: list[float]) -> float:
        arr = np.array(equity_curve)
        peaks = np.maximum.accumulate(arr)
        dd = (peaks - arr) / np.where(peaks > 0, peaks, 1)
        return round(float(np.max(dd)) * 100, 4) if len(dd) > 0 else 0.0

    @staticmethod
    def _sharpe(equity_curve: list[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0
        returns = np.diff(equity_curve) / equity_curve[:-1]
        std = np.std(returns)
        if std == 0:
            return 0.0
        return round(float(np.mean(returns) / std * np.sqrt(252)), 4)


def _percentiles(values: list[float]) -> dict[str, float]:
    arr = np.array(values)
    return {
        "p5": round(float(np.percentile(arr, 5)), 4),
        "p50": round(float(np.percentile(arr, 50)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
    }
