"""Tests for statistical significance testing."""

import pytest
from trading_system.backtesting.significance import permutation_test


class TestPermutationTest:
    def test_strong_signal_is_significant(self):
        pnls = [100, 80, 90, 110, 95, 105, 85, 120, 70, 100]
        result = permutation_test(pnls, num_permutations=5000, seed=42)

        assert result["is_significant"] is True
        assert result["p_value"] < 0.05
        assert result["observed_mean"] > 0

    def test_noise_is_not_significant(self):
        pnls = [1, -1, 1, -1, 0.5, -0.5, 0.2, -0.3]
        result = permutation_test(pnls, num_permutations=5000, seed=42)

        assert result["is_significant"] is False
        assert result["p_value"] > 0.05

    def test_empty_pnls(self):
        result = permutation_test([], num_permutations=100)

        assert result["p_value"] == 1.0
        assert result["is_significant"] is False

    def test_deterministic_with_seed(self):
        pnls = [10, 20, -5, 15, -3, 8, 12]
        r1 = permutation_test(pnls, seed=42)
        r2 = permutation_test(pnls, seed=42)

        assert r1["p_value"] == r2["p_value"]
