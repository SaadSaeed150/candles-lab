"""
Strategy comparator — runs multiple strategies on the same dataset
and produces a side-by-side comparison.

Useful for:
    - Selecting the best strategy for a given market
    - A/B testing strategy variants
    - Validating improvements to existing strategies
"""

from __future__ import annotations

import logging
from typing import Any

from trading_system.backtesting.report import generate_comparison
from trading_system.backtesting.runner import BacktestConfig, BacktestResult, BacktestRunner

logger = logging.getLogger(__name__)


class StrategyComparator:
    """Run multiple strategies on the same data and compare results.

    Usage:
        comparator = StrategyComparator(
            strategies=["strategy_a", "strategy_b", "strategy_c"],
            symbol="BTCUSDT",
            exchange="binance",
            timeframe="1m",
        )
        comparison = comparator.run()
        print(comparison["ranked_by_sharpe"])
    """

    def __init__(
        self,
        strategies: list[str],
        symbol: str = "BTCUSDT",
        exchange: str = "binance",
        timeframe: str = "1m",
        start: Any = None,
        end: Any = None,
        initial_balance: float = 10_000.0,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        feed_source: str = "database",
        csv_path: str | None = None,
        synthetic_points: int = 100,
        synthetic_start_price: float = 100.0,
    ) -> None:
        self.strategies = strategies
        self._base_kwargs = {
            "symbol": symbol,
            "exchange": exchange,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "initial_balance": initial_balance,
            "commission_rate": commission_rate,
            "slippage_rate": slippage_rate,
            "feed_source": feed_source,
            "csv_path": csv_path,
            "synthetic_points": synthetic_points,
            "synthetic_start_price": synthetic_start_price,
        }

    def run(self) -> dict[str, Any]:
        """Run all strategies and return the comparison report."""
        results: list[BacktestResult] = []

        for strategy_name in self.strategies:
            logger.info("Running backtest for strategy: %s", strategy_name)

            config = BacktestConfig(
                strategy_name=strategy_name,
                **self._base_kwargs,
            )
            runner = BacktestRunner(config)
            result = runner.run()
            results.append(result)

            logger.info(
                "  %s: return=%.2f%% sharpe=%.2f trades=%d",
                strategy_name,
                result.metrics.get("return_pct", 0),
                result.metrics.get("sharpe_ratio", 0),
                result.metrics.get("total_trades", 0),
            )

        self._results = results
        return generate_comparison(results)

    @property
    def results(self) -> list[BacktestResult]:
        """Access individual BacktestResult objects after run()."""
        return getattr(self, "_results", [])
