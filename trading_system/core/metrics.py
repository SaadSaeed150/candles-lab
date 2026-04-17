"""
Performance metrics for evaluating trading strategies.

All metrics operate on lists of Trade objects and equity snapshots,
making them usable after any backtest, paper, or live session.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def calculate_metrics(
    trades: list,
    equity_snapshots: list[dict],
    initial_balance: float = 10_000.0,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """Compute a full suite of performance metrics.

    Args:
        trades:           List of Trade objects (must have .pnl, .net_pnl).
        equity_snapshots: List of dicts with 'total_equity' and 'drawdown'.
        initial_balance:  Starting capital.
        risk_free_rate:   Annual risk-free rate for Sharpe/Sortino.
        periods_per_year: Trading periods per year (252 for daily, 365*24*60 for 1m crypto).

    Returns:
        Dict with all computed metrics.
    """
    if not trades:
        return _empty_metrics()

    pnls = [t.pnl for t in trades]
    net_pnls = [t.net_pnl for t in trades]
    equities = [s["total_equity"] for s in equity_snapshots] if equity_snapshots else [initial_balance]

    total_pnl = sum(pnls)
    total_net_pnl = sum(net_pnls)
    total_commission = sum(t.commission for t in trades)
    total_slippage = sum(t.slippage for t in trades)

    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p < 0]
    win_count = len(wins)
    loss_count = len(losses)

    final_equity = equities[-1] if equities else initial_balance

    return {
        "total_trades": len(trades),
        "total_pnl": round(total_pnl, 4),
        "total_net_pnl": round(total_net_pnl, 4),
        "total_commission": round(total_commission, 4),
        "total_slippage": round(total_slippage, 4),
        "final_equity": round(final_equity, 4),
        "return_pct": round((final_equity - initial_balance) / initial_balance * 100, 4),

        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_count / len(trades) * 100, 2) if trades else 0,
        "avg_win": round(np.mean(wins), 4) if wins else 0,
        "avg_loss": round(np.mean(losses), 4) if losses else 0,
        "largest_win": round(max(wins), 4) if wins else 0,
        "largest_loss": round(min(losses), 4) if losses else 0,
        "avg_trade": round(np.mean(net_pnls), 4),

        "profit_factor": _profit_factor(wins, losses),
        "payoff_ratio": _payoff_ratio(wins, losses),
        "expectancy": _expectancy(wins, losses, len(trades)),

        "sharpe_ratio": _sharpe_ratio(equities, risk_free_rate, periods_per_year),
        "sortino_ratio": _sortino_ratio(equities, risk_free_rate, periods_per_year),
        "calmar_ratio": _calmar_ratio(equities, initial_balance, periods_per_year),

        "max_drawdown_pct": _max_drawdown(equities),
        "max_consecutive_wins": _max_consecutive(net_pnls, positive=True),
        "max_consecutive_losses": _max_consecutive(net_pnls, positive=False),

        "cagr": _cagr(initial_balance, final_equity, len(equities), periods_per_year),
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_trades": 0, "total_pnl": 0, "total_net_pnl": 0,
        "total_commission": 0, "total_slippage": 0, "final_equity": 0,
        "return_pct": 0, "win_count": 0, "loss_count": 0,
        "win_rate": 0, "avg_win": 0, "avg_loss": 0,
        "largest_win": 0, "largest_loss": 0, "avg_trade": 0,
        "profit_factor": 0, "payoff_ratio": 0, "expectancy": 0,
        "sharpe_ratio": 0, "sortino_ratio": 0, "calmar_ratio": 0,
        "max_drawdown_pct": 0, "max_consecutive_wins": 0,
        "max_consecutive_losses": 0, "cagr": 0,
    }


def _profit_factor(wins: list[float], losses: list[float]) -> float:
    """Gross profit / gross loss. > 1 is profitable."""
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0
    return round(gross_profit / gross_loss, 4)


def _payoff_ratio(wins: list[float], losses: list[float]) -> float:
    """Average win / average loss."""
    avg_w = np.mean(wins) if wins else 0
    avg_l = abs(np.mean(losses)) if losses else 0
    if avg_l == 0:
        return float("inf") if avg_w > 0 else 0
    return round(avg_w / avg_l, 4)


def _expectancy(wins: list[float], losses: list[float], total: int) -> float:
    """Expected value per trade."""
    if total == 0:
        return 0
    win_rate = len(wins) / total
    loss_rate = len(losses) / total
    avg_w = np.mean(wins) if wins else 0
    avg_l = abs(np.mean(losses)) if losses else 0
    return round(win_rate * avg_w - loss_rate * avg_l, 4)


def _sharpe_ratio(
    equities: list[float],
    risk_free_rate: float,
    periods_per_year: int,
) -> float:
    """Annualised Sharpe ratio from equity curve."""
    if len(equities) < 2:
        return 0
    returns = np.diff(equities) / equities[:-1]
    if len(returns) == 0 or np.std(returns) == 0:
        return 0
    excess = returns - risk_free_rate / periods_per_year
    return round(float(np.mean(excess) / np.std(excess) * math.sqrt(periods_per_year)), 4)


def _sortino_ratio(
    equities: list[float],
    risk_free_rate: float,
    periods_per_year: int,
) -> float:
    """Annualised Sortino ratio (only penalises downside volatility)."""
    if len(equities) < 2:
        return 0
    returns = np.diff(equities) / equities[:-1]
    excess = returns - risk_free_rate / periods_per_year
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float("inf") if np.mean(excess) > 0 else 0
    downside_std = float(np.std(downside))
    if downside_std == 0:
        return 0
    return round(float(np.mean(excess) / downside_std * math.sqrt(periods_per_year)), 4)


def _calmar_ratio(
    equities: list[float],
    initial_balance: float,
    periods_per_year: int,
) -> float:
    """CAGR / max drawdown."""
    max_dd = _max_drawdown(equities)
    if max_dd == 0:
        return 0
    cagr = _cagr(initial_balance, equities[-1], len(equities), periods_per_year)
    return round(cagr / max_dd, 4) if max_dd != 0 else 0


def _max_drawdown(equities: list[float]) -> float:
    """Maximum peak-to-trough drawdown as a percentage."""
    if len(equities) < 2:
        return 0
    arr = np.array(equities)
    peaks = np.maximum.accumulate(arr)
    drawdowns = (peaks - arr) / peaks
    drawdowns = drawdowns[~np.isnan(drawdowns)]
    return round(float(np.max(drawdowns)) * 100, 4) if len(drawdowns) > 0 else 0


def _max_consecutive(pnls: list[float], positive: bool) -> int:
    """Longest consecutive streak of wins or losses."""
    max_streak = 0
    current = 0
    for p in pnls:
        if (positive and p > 0) or (not positive and p < 0):
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _cagr(
    initial: float,
    final: float,
    num_periods: int,
    periods_per_year: int,
) -> float:
    """Compound Annual Growth Rate."""
    if initial <= 0 or final <= 0 or num_periods <= 0:
        return 0
    years = num_periods / periods_per_year
    if years == 0:
        return 0
    return round((final / initial) ** (1 / years) - 1, 6)
