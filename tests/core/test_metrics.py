"""Tests for performance metric calculations."""

import pytest
from trading_system.core.metrics import calculate_metrics


class TestBasicMetrics:
    def test_total_trades(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["total_trades"] == 5

    def test_total_pnl(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        expected = 100 + (-50) + 100 + 50 + (-30)
        assert metrics["total_pnl"] == expected

    def test_net_pnl_accounts_for_fees(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["total_net_pnl"] < metrics["total_pnl"]
        assert metrics["total_commission"] == 10.0
        assert metrics["total_slippage"] == 5.0

    def test_win_rate(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["win_count"] == 3
        assert metrics["loss_count"] == 2
        assert metrics["win_rate"] == 60.0

    def test_empty_trades_returns_zeros(self):
        metrics = calculate_metrics([], [], initial_balance=10_000)
        assert metrics["total_trades"] == 0
        assert metrics["sharpe_ratio"] == 0
        assert metrics["win_rate"] == 0


class TestRatios:
    def test_profit_factor(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["profit_factor"] > 1

    def test_profit_factor_all_wins(self):
        from trading_system.core.trader import Trade
        wins = [
            Trade("BTC", "LONG", 100, 110, 10, 100, 0, 0, "", ""),
            Trade("BTC", "LONG", 100, 115, 10, 150, 0, 0, "", ""),
        ]
        metrics = calculate_metrics(wins, [], initial_balance=10_000)
        assert metrics["profit_factor"] == float("inf")


class TestDrawdown:
    def test_max_drawdown_from_equity(self, sample_trades):
        snapshots = [
            {"total_equity": 10000},
            {"total_equity": 10500},
            {"total_equity": 9500},
            {"total_equity": 10200},
            {"total_equity": 9800},
        ]
        metrics = calculate_metrics(sample_trades, snapshots, initial_balance=10_000)
        assert metrics["max_drawdown_pct"] > 0

    def test_zero_drawdown_monotonic_increase(self, sample_trades):
        snapshots = [
            {"total_equity": 10000},
            {"total_equity": 10100},
            {"total_equity": 10200},
        ]
        metrics = calculate_metrics(sample_trades, snapshots, initial_balance=10_000)
        assert metrics["max_drawdown_pct"] == 0.0


class TestSharpe:
    def test_sharpe_positive_for_uptrend(self, sample_trades):
        snapshots = [{"total_equity": 10000 + i * 100} for i in range(50)]
        metrics = calculate_metrics(sample_trades, snapshots, initial_balance=10_000)
        assert metrics["sharpe_ratio"] > 0

    def test_sharpe_zero_for_flat(self, sample_trades):
        snapshots = [{"total_equity": 10000} for _ in range(50)]
        metrics = calculate_metrics(sample_trades, snapshots, initial_balance=10_000)
        assert metrics["sharpe_ratio"] == 0


class TestConsecutive:
    def test_max_consecutive_wins(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["max_consecutive_wins"] >= 1

    def test_max_consecutive_losses(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["max_consecutive_losses"] >= 1


class TestBenchmark:
    def test_benchmark_return_computed(self, sample_trades):
        metrics = calculate_metrics(
            sample_trades, [], initial_balance=10_000,
            first_price=100.0, last_price=120.0,
        )
        assert metrics["benchmark_return_pct"] == pytest.approx(20.0, abs=0.01)

    def test_alpha_positive_when_strategy_beats_benchmark(self, sample_trades):
        snapshots = [{"total_equity": 10_000 + i * 200} for i in range(50)]
        metrics = calculate_metrics(
            sample_trades, snapshots, initial_balance=10_000,
            first_price=100.0, last_price=105.0,
        )
        assert metrics["alpha"] > 0

    def test_no_prices_gives_zero_benchmark(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["benchmark_return_pct"] == 0
        assert metrics["alpha"] == 0


class TestRecoveryFactor:
    def test_positive_recovery_factor(self, sample_trades):
        snapshots = [
            {"total_equity": 10000},
            {"total_equity": 10500},
            {"total_equity": 9500},
            {"total_equity": 10200},
        ]
        metrics = calculate_metrics(sample_trades, snapshots, initial_balance=10_000)
        assert metrics["recovery_factor"] != 0


class TestTailRatio:
    def test_tail_ratio_computed(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert "tail_ratio" in metrics

    def test_tail_ratio_positive_for_good_strategy(self):
        from trading_system.core.trader import Trade
        trades = [
            Trade("BTC", "LONG", 100, 120, 10, 200, 0, 0, "", ""),
            Trade("BTC", "LONG", 100, 105, 10, 50, 0, 0, "", ""),
            Trade("BTC", "LONG", 100, 98, 10, -20, 0, 0, "", ""),
        ]
        metrics = calculate_metrics(trades, [], initial_balance=10_000)
        assert metrics["tail_ratio"] > 0


class TestCAGR:
    def test_cagr_fence_post(self, sample_trades):
        snapshots = [{"total_equity": 10000 + i * 10} for i in range(253)]
        metrics = calculate_metrics(
            sample_trades, snapshots, initial_balance=10_000,
            periods_per_year=252,
        )
        assert metrics["cagr"] > 0

    def test_single_snapshot_gives_zero_cagr(self, sample_trades):
        snapshots = [{"total_equity": 11000}]
        metrics = calculate_metrics(sample_trades, snapshots, initial_balance=10_000)
        assert metrics["cagr"] == 0


class TestAvgHoldingPeriod:
    def test_holding_period_string_returned(self, sample_trades):
        metrics = calculate_metrics(sample_trades, [], initial_balance=10_000)
        assert metrics["avg_holding_period"] is not None
        assert isinstance(metrics["avg_holding_period"], str)
