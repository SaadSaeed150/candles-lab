"""
Statistical significance testing for trading strategies.

Uses a permutation test to determine whether a strategy's mean PnL
is significantly different from zero (i.e. not explainable by luck).
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np


def permutation_test(
    trade_pnls: list[float],
    num_permutations: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Test whether the observed mean PnL is statistically significant.

    Randomly flips the sign of each trade PnL to simulate a world
    where the strategy has no edge. Counts how often the permuted
    mean exceeds the observed mean.

    Args:
        trade_pnls:       Net PnL of each completed trade.
        num_permutations: Number of random permutations to run.
        seed:             Random seed for reproducibility.

    Returns:
        Dict with p_value, is_significant (at 0.05), and observed_mean.
    """
    if not trade_pnls:
        return {"p_value": 1.0, "is_significant": False, "observed_mean": 0.0}

    rng = random.Random(seed)
    observed_mean = float(np.mean(trade_pnls))
    abs_observed = abs(observed_mean)
    pnls = np.array(trade_pnls)

    count_extreme = 0
    for _ in range(num_permutations):
        signs = np.array([rng.choice((-1, 1)) for _ in range(len(pnls))])
        permuted_mean = float(np.mean(pnls * signs))
        if abs(permuted_mean) >= abs_observed:
            count_extreme += 1

    p_value = count_extreme / num_permutations

    return {
        "p_value": round(p_value, 6),
        "is_significant": p_value < 0.05,
        "observed_mean": round(observed_mean, 4),
    }
