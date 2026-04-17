"""
Walk-forward optimization — prevents overfitting by splitting data
into rolling in-sample (training) and out-of-sample (validation) windows.

How it works:
    1. Divide the data range into N windows
    2. For each window, use the first portion as in-sample
    3. Run the strategy on in-sample to find optimal parameters
    4. Validate on the out-of-sample portion
    5. Aggregate out-of-sample results for the true performance estimate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from trading_system.backtesting.runner import BacktestConfig, BacktestResult, BacktestRunner

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward analysis."""

    base_config: BacktestConfig = field(default_factory=BacktestConfig)
    num_windows: int = 5
    in_sample_pct: float = 0.7
    parameter_sets: list[dict[str, Any]] = field(default_factory=list)
    optimization_metric: str = "sharpe_ratio"


@dataclass
class WindowResult:
    """Result for a single walk-forward window."""

    window_index: int
    in_sample_start: datetime
    in_sample_end: datetime
    out_of_sample_start: datetime
    out_of_sample_end: datetime
    best_params: dict[str, Any]
    in_sample_metric: float
    out_of_sample_result: BacktestResult


@dataclass
class WalkForwardResult:
    """Aggregated result of the entire walk-forward analysis."""

    config: WalkForwardConfig
    window_results: list[WindowResult]
    aggregate_metrics: dict[str, Any]
    is_robust: bool

    def summary(self) -> dict[str, Any]:
        return {
            "num_windows": len(self.window_results),
            "is_robust": self.is_robust,
            "aggregate_metrics": self.aggregate_metrics,
            "windows": [
                {
                    "window": w.window_index,
                    "in_sample_metric": w.in_sample_metric,
                    "oos_return": w.out_of_sample_result.metrics.get("return_pct", 0),
                    "oos_sharpe": w.out_of_sample_result.metrics.get("sharpe_ratio", 0),
                    "oos_trades": w.out_of_sample_result.metrics.get("total_trades", 0),
                    "best_params": w.best_params,
                }
                for w in self.window_results
            ],
        }


class WalkForwardOptimizer:
    """Runs walk-forward optimization over a date range.

    Usage:
        config = WalkForwardConfig(
            base_config=BacktestConfig(strategy_name="my_strat", ...),
            num_windows=5,
            in_sample_pct=0.7,
            parameter_sets=[
                {"threshold_buy": 95, "threshold_sell": 110},
                {"threshold_buy": 100, "threshold_sell": 115},
            ],
        )
        optimizer = WalkForwardOptimizer(config)
        result = optimizer.run()
    """

    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config

    def run(self) -> WalkForwardResult:
        """Execute the walk-forward optimization."""
        windows = self._create_windows()
        window_results: list[WindowResult] = []

        for i, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
            logger.info(
                "Walk-forward window %d/%d: IS [%s → %s], OOS [%s → %s]",
                i + 1, len(windows), is_start, is_end, oos_start, oos_end,
            )

            best_params, best_metric = self._optimize_in_sample(is_start, is_end)
            oos_result = self._run_out_of_sample(oos_start, oos_end, best_params)

            window_results.append(WindowResult(
                window_index=i,
                in_sample_start=is_start,
                in_sample_end=is_end,
                out_of_sample_start=oos_start,
                out_of_sample_end=oos_end,
                best_params=best_params,
                in_sample_metric=best_metric,
                out_of_sample_result=oos_result,
            ))

        aggregate = self._aggregate_results(window_results)
        is_robust = self._check_robustness(window_results)

        return WalkForwardResult(
            config=self.config,
            window_results=window_results,
            aggregate_metrics=aggregate,
            is_robust=is_robust,
        )

    def _create_windows(self) -> list[tuple[datetime, datetime, datetime, datetime]]:
        """Split the date range into rolling windows."""
        start = self.config.base_config.start
        end = self.config.base_config.end

        if not start or not end:
            raise ValueError("start and end dates are required for walk-forward")

        total_duration = end - start
        window_duration = total_duration / self.config.num_windows
        is_duration = window_duration * self.config.in_sample_pct

        windows = []
        for i in range(self.config.num_windows):
            w_start = start + window_duration * i
            w_end = w_start + window_duration
            is_end = w_start + is_duration
            windows.append((w_start, is_end, is_end, w_end))

        return windows

    def _optimize_in_sample(
        self, start: datetime, end: datetime
    ) -> tuple[dict[str, Any], float]:
        """Run all parameter sets on in-sample data, return best."""
        if not self.config.parameter_sets:
            result = self._run_single(start, end, {})
            metric_val = result.metrics.get(self.config.optimization_metric, 0)
            return {}, metric_val

        best_params: dict[str, Any] = {}
        best_metric = float("-inf")

        for params in self.config.parameter_sets:
            result = self._run_single(start, end, params)
            metric_val = result.metrics.get(self.config.optimization_metric, 0)

            if metric_val > best_metric:
                best_metric = metric_val
                best_params = params

        return best_params, best_metric

    def _run_out_of_sample(
        self, start: datetime, end: datetime, params: dict[str, Any]
    ) -> BacktestResult:
        """Run the best parameters on out-of-sample data."""
        return self._run_single(start, end, params)

    def _run_single(
        self, start: datetime, end: datetime, params: dict[str, Any]
    ) -> BacktestResult:
        """Run a single backtest with the given date range and params."""
        config = BacktestConfig(
            strategy_name=self.config.base_config.strategy_name,
            symbol=self.config.base_config.symbol,
            exchange=self.config.base_config.exchange,
            timeframe=self.config.base_config.timeframe,
            start=start,
            end=end,
            initial_balance=self.config.base_config.initial_balance,
            commission_rate=self.config.base_config.commission_rate,
            slippage_rate=self.config.base_config.slippage_rate,
            position_sizing=self.config.base_config.position_sizing,
            position_size_value=self.config.base_config.position_size_value,
            max_positions=self.config.base_config.max_positions,
            risk_config=self.config.base_config.risk_config,
            feed_source=self.config.base_config.feed_source,
            csv_path=self.config.base_config.csv_path,
            synthetic_points=self.config.base_config.synthetic_points,
            synthetic_start_price=self.config.base_config.synthetic_start_price,
            random_seed=self.config.base_config.random_seed,
            strategy_params=params,
        )

        runner = BacktestRunner(config)
        return runner.run()

    @staticmethod
    def _aggregate_results(window_results: list[WindowResult]) -> dict[str, Any]:
        """Combine out-of-sample results across all windows."""
        if not window_results:
            return {}

        oos_metrics = [w.out_of_sample_result.metrics for w in window_results]

        keys = ["return_pct", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                "win_rate", "profit_factor", "total_trades", "total_net_pnl"]
        agg: dict[str, Any] = {}

        for key in keys:
            values = [m.get(key, 0) for m in oos_metrics]
            agg[f"avg_{key}"] = round(sum(values) / len(values), 4) if values else 0
            agg[f"min_{key}"] = round(min(values), 4) if values else 0
            agg[f"max_{key}"] = round(max(values), 4) if values else 0

        agg["total_oos_trades"] = sum(m.get("total_trades", 0) for m in oos_metrics)
        agg["total_oos_net_pnl"] = round(sum(m.get("total_net_pnl", 0) for m in oos_metrics), 4)

        return agg

    @staticmethod
    def _check_robustness(window_results: list[WindowResult]) -> bool:
        """A strategy is considered robust if >50% of OOS windows are profitable."""
        if not window_results:
            return False
        profitable = sum(
            1 for w in window_results
            if w.out_of_sample_result.metrics.get("total_net_pnl", 0) > 0
        )
        return profitable > len(window_results) / 2
