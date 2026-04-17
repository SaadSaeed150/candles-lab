#!/usr/bin/env python
"""
Standalone simulation runner — no Django server required.

Usage:
    python run_simulation.py [--strategy sample] [--points 50] [--balance 10000]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from trading_system.core import registry
from trading_system.core.engine import TradingEngine
from trading_system.core.risk import RiskConfig
from trading_system.core.trader import PaperTrader, PositionSizing
from trading_system.data.feed import generate_feed

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("simulation")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a paper-trading simulation")
    parser.add_argument("--strategy", default="sample", help="Registered strategy name")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--points", type=int, default=50, help="Number of data points")
    parser.add_argument("--balance", type=float, default=10_000.0, help="Starting balance")
    parser.add_argument("--start-price", type=float, default=105.0)
    parser.add_argument("--commission", type=float, default=0.001, help="Commission rate (e.g. 0.001 = 0.1%%)")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Max slippage rate")
    args = parser.parse_args(argv)

    registry.load_defaults()

    strategy_cls = registry.get(args.strategy)
    strategy = strategy_cls()
    trader = PaperTrader(
        balance=args.balance,
        commission_rate=args.commission,
        slippage_rate=args.slippage,
        position_sizing=PositionSizing.ALL_IN,
    )
    risk_config = RiskConfig(
        max_drawdown_pct=0.20,
        max_daily_loss_pct=0.05,
    )
    engine = TradingEngine(
        strategy=strategy,
        trader=trader,
        risk_config=risk_config,
        initial_balance=args.balance,
    )

    feed = generate_feed(
        symbol=args.symbol,
        start_price=args.start_price,
        num_points=args.points,
    )

    logger.info(
        "Starting simulation: strategy=%s symbol=%s points=%d balance=%.2f commission=%.3f%%",
        args.strategy, args.symbol, args.points, args.balance, args.commission * 100,
    )

    results = engine.run(feed)
    metrics = engine.compute_metrics()

    print("\n" + "=" * 60)
    print("SIMULATION COMPLETE")
    print("=" * 60)
    print(f"  Ticks processed : {len(results)}")
    print(f"  Trades completed: {metrics['total_trades']}")
    print(f"  Final equity    : {metrics['final_equity']:.2f}")
    print(f"  Total PnL       : {metrics['total_pnl']:+.2f}")
    print(f"  Net PnL (after fees): {metrics['total_net_pnl']:+.2f}")
    print(f"  Commission paid : {metrics['total_commission']:.2f}")
    print(f"  Return          : {metrics['return_pct']:+.2f}%")

    print(f"\n  Win rate        : {metrics['win_rate']:.1f}%")
    print(f"  Avg win         : {metrics['avg_win']:+.2f}")
    print(f"  Avg loss        : {metrics['avg_loss']:+.2f}")
    print(f"  Profit factor   : {metrics['profit_factor']:.2f}")
    print(f"  Expectancy      : {metrics['expectancy']:+.2f}")

    print(f"\n  Sharpe ratio    : {metrics['sharpe_ratio']:.2f}")
    print(f"  Sortino ratio   : {metrics['sortino_ratio']:.2f}")
    print(f"  Max drawdown    : {metrics['max_drawdown_pct']:.2f}%")

    if engine.trade_history:
        print("\n  Trade log:")
        for i, t in enumerate(engine.trade_history, 1):
            print(
                f"    {i}. {t['side']} {t['symbol']}  "
                f"entry={t['entry_price']:.2f}  exit={t['exit_price']:.2f}  "
                f"pnl={t['pnl']:+.2f}  net={t['net_pnl']:+.2f}  "
                f"comm={t['commission']:.2f}"
            )

    if trader.positions:
        last_close = results[-1]["data"]["close"]
        unrealised = trader.total_unrealised_pnl(last_close)
        for sym, pos in trader.positions.items():
            print(f"\n  Open position: {pos.side} {sym} @ {pos.entry_price:.2f}")
        print(f"  Unrealised PnL: {unrealised:+.2f}")

    print("=" * 60)


if __name__ == "__main__":
    main()
