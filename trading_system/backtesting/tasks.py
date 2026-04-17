"""
Celery tasks for running backtests in the background.

Each task persists its results to StrategyRun, TradeRecord,
StrategySignal, and EquityCurve models so the frontend can
display them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import shared_task
from django.utils import timezone as tz

from trading_system.backtesting.runner import BacktestConfig, BacktestRunner
from trading_system.core.risk import RiskConfig
from trading_system.core.trader import PositionSizing
from trading_system.data.models import (
    EquityCurve,
    StrategyRun,
    StrategySignal,
    TradeRecord,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@shared_task(bind=True, name="backtesting.run_backtest")
def run_backtest(
    self,
    strategy_name: str,
    symbol: str,
    exchange: str = "binance",
    timeframe: str = "1m",
    start: str | None = None,
    end: str | None = None,
    initial_balance: float = 10_000.0,
    commission_rate: float = 0.001,
    slippage_rate: float = 0.0005,
    position_sizing: str = "all_in",
    position_size_value: float = 0.0,
    max_positions: int = 1,
    feed_source: str = "synthetic",
    csv_path: str | None = None,
    synthetic_points: int = 100,
    synthetic_start_price: float = 100.0,
    user_id: int | None = None,
    max_drawdown_pct: float = 0.20,
) -> dict:
    """Run a backtest and persist results to the database.

    Returns the StrategyRun ID and summary metrics.
    """
    run = StrategyRun.objects.create(
        user_id=user_id,
        strategy_name=strategy_name,
        mode="backtest",
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        config={
            "initial_balance": initial_balance,
            "commission_rate": commission_rate,
            "slippage_rate": slippage_rate,
            "position_sizing": position_sizing,
            "feed_source": feed_source,
        },
        status="running",
        initial_balance=initial_balance,
    )

    try:
        sizing_enum = PositionSizing(position_sizing)
    except ValueError:
        sizing_enum = PositionSizing.ALL_IN

    config = BacktestConfig(
        strategy_name=strategy_name,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        start=_parse_dt(start),
        end=_parse_dt(end),
        initial_balance=initial_balance,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        position_sizing=sizing_enum,
        position_size_value=position_size_value,
        max_positions=max_positions,
        risk_config=RiskConfig(max_drawdown_pct=max_drawdown_pct),
        feed_source=feed_source,
        csv_path=csv_path,
        synthetic_points=synthetic_points,
        synthetic_start_price=synthetic_start_price,
    )

    def on_progress(tick: int, total: int):
        self.update_state(state="PROGRESS", meta={"ticks": tick, "total": total})

    try:
        runner = BacktestRunner(config, on_progress=on_progress)
        result = runner.run()
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = tz.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        raise

    run.status = "completed"
    run.finished_at = tz.now()
    run.final_balance = result.metrics.get("final_equity", initial_balance)
    run.metrics = result.metrics
    run.save(update_fields=["status", "finished_at", "final_balance", "metrics"])

    _persist_trades(run, result.trades, user_id)
    _persist_signals(run, result.signals)
    _persist_equity_curve(run, result.equity_snapshots)

    logger.info("Backtest run %d complete: %s", run.id, result.metrics.get("return_pct"))

    return {
        "run_id": run.id,
        "summary": result.summary(),
    }


@shared_task(bind=True, name="backtesting.compare_strategies")
def compare_strategies(
    self,
    strategy_names: list[str],
    symbol: str = "BTCUSDT",
    exchange: str = "binance",
    timeframe: str = "1m",
    initial_balance: float = 10_000.0,
    feed_source: str = "synthetic",
    synthetic_points: int = 100,
    user_id: int | None = None,
) -> dict:
    """Run multiple strategies and return comparison."""
    from trading_system.backtesting.compare import StrategyComparator

    comparator = StrategyComparator(
        strategies=strategy_names,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        initial_balance=initial_balance,
        feed_source=feed_source,
        synthetic_points=synthetic_points,
    )
    comparison = comparator.run()

    for result in comparator.results:
        run = StrategyRun.objects.create(
            user_id=user_id,
            strategy_name=result.config.strategy_name,
            mode="backtest",
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            status="completed",
            initial_balance=initial_balance,
            final_balance=result.metrics.get("final_equity"),
            finished_at=tz.now(),
            metrics=result.metrics,
        )
        _persist_trades(run, result.trades, user_id)

    return comparison


def _persist_trades(run: StrategyRun, trades: list[dict], user_id: int | None) -> None:
    """Bulk-create TradeRecord objects."""
    objects = [
        TradeRecord(
            user_id=user_id,
            run=run,
            symbol=t.get("symbol", run.symbol),
            exchange=run.exchange,
            side=t["side"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            quantity=t["quantity"],
            pnl=t["pnl"],
            commission=t.get("commission", 0),
            slippage=t.get("slippage", 0),
            opened_at=t["opened_at"],
            closed_at=t["closed_at"],
        )
        for t in trades
    ]
    TradeRecord.objects.bulk_create(objects, batch_size=500)


def _persist_signals(run: StrategyRun, signals: list[dict]) -> None:
    """Bulk-create StrategySignal objects."""
    objects = [
        StrategySignal(
            run=run,
            timestamp=s["timestamp"],
            action=s["action"],
            price=s["price"],
            confidence=s.get("confidence"),
            stop_loss=s.get("stop_loss"),
            take_profit=s.get("take_profit"),
            meta=s.get("meta", {}),
        )
        for s in signals
        if s.get("timestamp")
    ]
    StrategySignal.objects.bulk_create(objects, batch_size=500)


def _persist_equity_curve(run: StrategyRun, snapshots: list[dict]) -> None:
    """Bulk-create EquityCurve objects (downsampled for large datasets)."""
    max_points = 1000
    if len(snapshots) > max_points:
        step = len(snapshots) // max_points
        snapshots = snapshots[::step]
        if snapshots[-1] != snapshots[-1]:
            pass

    objects = [
        EquityCurve(
            run=run,
            timestamp=s["timestamp"],
            balance=s["balance"],
            unrealised_pnl=s.get("unrealised_pnl", 0),
            total_equity=s["total_equity"],
            drawdown=s.get("drawdown", 0),
        )
        for s in snapshots
        if s.get("timestamp")
    ]
    EquityCurve.objects.bulk_create(objects, batch_size=500)
