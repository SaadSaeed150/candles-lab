"""Tests for Monte Carlo simulation."""

import pytest
from trading_system.core.trader import Trade
from trading_system.backtesting.monte_carlo import MonteCarloSimulator


@pytest.fixture
def sample_trades():
    return [
        Trade("BTC", "LONG", 100, 110, 10, 100, 2, 1, "2026-01-01", "2026-01-02"),
        Trade("BTC", "LONG", 110, 105, 10, -50, 2, 1, "2026-01-02", "2026-01-03"),
        Trade("BTC", "SHORT", 105, 95, 10, 100, 2, 1, "2026-01-03", "2026-01-04"),
        Trade("BTC", "LONG", 95, 100, 10, 50, 2, 1, "2026-01-04", "2026-01-05"),
        Trade("BTC", "SHORT", 100, 103, 10, -30, 2, 1, "2026-01-05", "2026-01-06"),
    ]


class TestMonteCarloSimulator:
    def test_returns_percentiles(self, sample_trades):
        sim = MonteCarloSimulator(sample_trades, initial_balance=10_000, num_simulations=100)
        result = sim.run()

        assert "p5" in result.final_equity
        assert "p50" in result.final_equity
        assert "p95" in result.final_equity
        assert result.final_equity["p5"] <= result.final_equity["p50"] <= result.final_equity["p95"]

    def test_deterministic_with_seed(self, sample_trades):
        r1 = MonteCarloSimulator(sample_trades, seed=42, num_simulations=100).run()
        r2 = MonteCarloSimulator(sample_trades, seed=42, num_simulations=100).run()

        assert r1.final_equity == r2.final_equity
        assert r1.max_drawdown_pct == r2.max_drawdown_pct

    def test_empty_trades(self):
        result = MonteCarloSimulator([], initial_balance=10_000).run()
        assert result.num_simulations == 0
        assert result.final_equity["p50"] == 0.0

    def test_summary_contains_all_keys(self, sample_trades):
        result = MonteCarloSimulator(sample_trades, num_simulations=50).run()
        summary = result.summary()

        assert "num_simulations" in summary
        assert "final_equity" in summary
        assert "max_drawdown_pct" in summary
        assert "sharpe_ratio" in summary
