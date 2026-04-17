"""Tests for the BacktestRunner."""

import pytest
from trading_system.backtesting.runner import BacktestConfig, BacktestRunner, BacktestResult
from trading_system.backtesting.report import generate_summary, generate_detailed


class TestBacktestRunner:
    def test_synthetic_backtest_runs(self):
        config = BacktestConfig(
            strategy_name="sample",
            feed_source="synthetic",
            synthetic_points=50,
            synthetic_start_price=100.0,
            initial_balance=10_000,
            commission_rate=0,
            slippage_rate=0,
        )
        runner = BacktestRunner(config)
        result = runner.run()

        assert isinstance(result, BacktestResult)
        assert result.ticks_processed == 50
        assert result.duration_seconds >= 0
        assert len(result.signals) == 50

    def test_metrics_computed(self):
        config = BacktestConfig(
            strategy_name="sample",
            feed_source="synthetic",
            synthetic_points=100,
            initial_balance=10_000,
        )
        runner = BacktestRunner(config)
        result = runner.run()

        assert "total_trades" in result.metrics
        assert "sharpe_ratio" in result.metrics
        assert "win_rate" in result.metrics

    def test_progress_callback(self):
        progress_calls = []

        def on_progress(tick, total):
            progress_calls.append(tick)

        config = BacktestConfig(
            strategy_name="sample",
            feed_source="synthetic",
            synthetic_points=250,
        )
        runner = BacktestRunner(config, on_progress=on_progress)
        runner.run()

        assert len(progress_calls) >= 2

    def test_summary_has_key_fields(self):
        config = BacktestConfig(
            strategy_name="sample",
            feed_source="synthetic",
            synthetic_points=50,
        )
        runner = BacktestRunner(config)
        result = runner.run()
        summary = result.summary()

        assert "strategy" in summary
        assert "symbol" in summary
        assert "ticks_processed" in summary

    def test_invalid_feed_source_raises(self):
        config = BacktestConfig(
            strategy_name="sample",
            feed_source="nonexistent",
        )
        runner = BacktestRunner(config)

        with pytest.raises(ValueError, match="Unknown feed source"):
            runner.run()

    def test_invalid_strategy_raises(self):
        config = BacktestConfig(
            strategy_name="does_not_exist",
            feed_source="synthetic",
            synthetic_points=10,
        )
        runner = BacktestRunner(config)

        with pytest.raises(KeyError):
            runner.run()


class TestBacktestReport:
    def test_summary_report_structure(self):
        config = BacktestConfig(
            strategy_name="sample",
            feed_source="synthetic",
            synthetic_points=50,
        )
        result = BacktestRunner(config).run()
        summary = generate_summary(result)

        assert "overview" in summary
        assert "performance" in summary
        assert "pnl" in summary

    def test_detailed_report_includes_trades(self):
        config = BacktestConfig(
            strategy_name="sample",
            feed_source="synthetic",
            synthetic_points=50,
        )
        result = BacktestRunner(config).run()
        report = generate_detailed(result)

        assert "trades" in report
        assert "equity_curve" in report
        assert "trade_distribution" in report
        assert "monthly_returns" in report
        assert "signals_count" in report


class TestBacktestComparator:
    def test_compare_single_strategy(self):
        from trading_system.backtesting.compare import StrategyComparator

        comp = StrategyComparator(
            strategies=["sample", "sample"],
            feed_source="synthetic",
            synthetic_points=50,
        )
        result = comp.run()

        assert "strategies" in result
        assert len(result["strategies"]) == 2
        assert "ranked_by_sharpe" in result
