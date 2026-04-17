"""
Report generator — transforms backtest results into structured reports
suitable for API responses and frontend rendering.

Produces:
    - Summary report (key metrics at a glance)
    - Detailed report (full trade log, equity curve, signal breakdown)
    - Comparison report (side-by-side metrics for multiple strategies)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from trading_system.backtesting.runner import BacktestResult

logger = logging.getLogger(__name__)


def generate_summary(result: BacktestResult) -> dict[str, Any]:
    """Generate a compact summary report."""
    m = result.metrics
    return {
        "overview": {
            "strategy": result.config.strategy_name,
            "symbol": result.config.symbol,
            "exchange": result.config.exchange,
            "timeframe": result.config.timeframe,
            "initial_balance": result.config.initial_balance,
            "final_equity": m.get("final_equity", 0),
            "return_pct": m.get("return_pct", 0),
            "ticks_processed": result.ticks_processed,
            "duration_seconds": round(result.duration_seconds, 2),
        },
        "performance": {
            "total_trades": m.get("total_trades", 0),
            "win_rate": m.get("win_rate", 0),
            "profit_factor": m.get("profit_factor", 0),
            "sharpe_ratio": m.get("sharpe_ratio", 0),
            "sortino_ratio": m.get("sortino_ratio", 0),
            "max_drawdown_pct": m.get("max_drawdown_pct", 0),
            "calmar_ratio": m.get("calmar_ratio", 0),
        },
        "pnl": {
            "total_pnl": m.get("total_pnl", 0),
            "total_net_pnl": m.get("total_net_pnl", 0),
            "total_commission": m.get("total_commission", 0),
            "total_slippage": m.get("total_slippage", 0),
            "avg_trade": m.get("avg_trade", 0),
            "expectancy": m.get("expectancy", 0),
        },
    }


def generate_detailed(result: BacktestResult) -> dict[str, Any]:
    """Generate a full detailed report with trade log and equity curve."""
    summary = generate_summary(result)

    summary["trades"] = result.trades
    summary["signals_count"] = len(result.signals)
    summary["equity_curve"] = _build_equity_curve(result.equity_snapshots)
    summary["trade_distribution"] = _trade_distribution(result.trades)
    summary["monthly_returns"] = _monthly_returns(result.trades)

    return summary


def generate_comparison(results: list[BacktestResult]) -> dict[str, Any]:
    """Generate a side-by-side comparison of multiple backtest results."""
    strategies = []

    for result in results:
        m = result.metrics
        strategies.append({
            "strategy": result.config.strategy_name,
            "symbol": result.config.symbol,
            "total_trades": m.get("total_trades", 0),
            "return_pct": m.get("return_pct", 0),
            "win_rate": m.get("win_rate", 0),
            "profit_factor": m.get("profit_factor", 0),
            "sharpe_ratio": m.get("sharpe_ratio", 0),
            "sortino_ratio": m.get("sortino_ratio", 0),
            "max_drawdown_pct": m.get("max_drawdown_pct", 0),
            "calmar_ratio": m.get("calmar_ratio", 0),
            "total_net_pnl": m.get("total_net_pnl", 0),
            "expectancy": m.get("expectancy", 0),
            "total_commission": m.get("total_commission", 0),
        })

    ranked = sorted(strategies, key=lambda s: s["sharpe_ratio"], reverse=True)

    return {
        "strategies": strategies,
        "ranked_by_sharpe": [s["strategy"] for s in ranked],
        "best_return": max(strategies, key=lambda s: s["return_pct"])["strategy"],
        "best_sharpe": ranked[0]["strategy"] if ranked else None,
        "lowest_drawdown": min(strategies, key=lambda s: s["max_drawdown_pct"])["strategy"],
    }


def _build_equity_curve(snapshots: list[dict]) -> list[dict]:
    """Downsample equity snapshots for chart rendering."""
    if not snapshots:
        return []

    max_points = 500
    if len(snapshots) <= max_points:
        return snapshots

    step = len(snapshots) // max_points
    sampled = snapshots[::step]
    if snapshots[-1] not in sampled:
        sampled.append(snapshots[-1])
    return sampled


def _trade_distribution(trades: list[dict]) -> dict[str, Any]:
    """Breakdown of trades by side and outcome."""
    long_wins = sum(1 for t in trades if t.get("side") == "LONG" and t.get("net_pnl", t.get("pnl", 0)) > 0)
    long_losses = sum(1 for t in trades if t.get("side") == "LONG" and t.get("net_pnl", t.get("pnl", 0)) <= 0)
    short_wins = sum(1 for t in trades if t.get("side") == "SHORT" and t.get("net_pnl", t.get("pnl", 0)) > 0)
    short_losses = sum(1 for t in trades if t.get("side") == "SHORT" and t.get("net_pnl", t.get("pnl", 0)) <= 0)

    return {
        "long_wins": long_wins,
        "long_losses": long_losses,
        "short_wins": short_wins,
        "short_losses": short_losses,
        "total_long": long_wins + long_losses,
        "total_short": short_wins + short_losses,
    }


def _monthly_returns(trades: list[dict]) -> list[dict]:
    """Aggregate PnL by month."""
    monthly: dict[str, float] = {}
    for t in trades:
        closed = t.get("closed_at", "")
        if not closed:
            continue
        try:
            if isinstance(closed, str):
                month_key = closed[:7]
            else:
                month_key = closed.strftime("%Y-%m")
        except (ValueError, AttributeError):
            continue
        monthly[month_key] = monthly.get(month_key, 0) + t.get("net_pnl", t.get("pnl", 0))

    return [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly.items())]
