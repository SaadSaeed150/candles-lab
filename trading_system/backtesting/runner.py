"""
Backtest runner — feeds historical data through the trading engine
and persists results to the database.

Supports:
    - Database-backed feeds (TimescaleDB candle data)
    - Synthetic feeds (for quick testing)
    - CSV file feeds
    - Full metrics computation and StrategyRun persistence
    - Equity curve persistence for charting
    - Progress callbacks for Celery task tracking
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator

from trading_system.core.engine import TradingEngine
from trading_system.core.risk import RiskConfig
from trading_system.core.trader import PaperTrader, PositionSizing

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    strategy_name: str = "sample"
    symbol: str = "BTCUSDT"
    exchange: str = "binance"
    timeframe: str = "1m"
    start: datetime | None = None
    end: datetime | None = None

    initial_balance: float = 10_000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005
    position_sizing: PositionSizing = PositionSizing.ALL_IN
    position_size_value: float = 0.0
    max_positions: int = 1

    risk_config: RiskConfig = field(default_factory=RiskConfig)
    periods_per_year: int = 252

    feed_source: str = "database"
    csv_path: str | None = None
    synthetic_points: int = 100
    synthetic_start_price: float = 100.0
    random_seed: int | None = None
    strategy_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""

    config: BacktestConfig
    metrics: dict[str, Any]
    trades: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    equity_snapshots: list[dict[str, Any]]
    ticks_processed: int
    duration_seconds: float
    engine: TradingEngine

    @property
    def is_profitable(self) -> bool:
        return self.metrics.get("total_net_pnl", 0) > 0

    def summary(self) -> dict[str, Any]:
        """Compact summary for API responses."""
        return {
            "strategy": self.config.strategy_name,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "ticks_processed": self.ticks_processed,
            "duration_seconds": round(self.duration_seconds, 2),
            "initial_balance": self.config.initial_balance,
            **{k: v for k, v in self.metrics.items()},
        }


class BacktestRunner:
    """Orchestrates a single backtest run.

    Usage:
        config = BacktestConfig(strategy_name="my_strategy", symbol="BTCUSDT")
        runner = BacktestRunner(config)
        result = runner.run()
        print(result.metrics)
    """

    def __init__(
        self,
        config: BacktestConfig,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self.config = config
        self.on_progress = on_progress

    def run(self) -> BacktestResult:
        """Execute the backtest and return the result."""
        from trading_system.core import registry
        registry.load_defaults()

        strategy_cls = registry.get(self.config.strategy_name)
        strategy = strategy_cls()
        if self.config.strategy_params:
            strategy.configure(self.config.strategy_params)

        trader = PaperTrader(
            balance=self.config.initial_balance,
            commission_rate=self.config.commission_rate,
            slippage_rate=self.config.slippage_rate,
            position_sizing=self.config.position_sizing,
            position_size_value=self.config.position_size_value,
            max_positions=self.config.max_positions,
            random_seed=self.config.random_seed,
        )

        engine = TradingEngine(
            strategy=strategy,
            trader=trader,
            risk_config=self.config.risk_config,
            initial_balance=self.config.initial_balance,
        )

        feed = self._build_feed()

        logger.info(
            "Starting backtest: %s on %s %s %s",
            self.config.strategy_name,
            self.config.exchange,
            self.config.symbol,
            self.config.timeframe,
        )

        start_time = time.monotonic()
        tick_count = 0

        for data_point in feed:
            engine.tick(data_point)
            tick_count += 1

            if self.on_progress and tick_count % 100 == 0:
                self.on_progress(tick_count, 0)

        duration = time.monotonic() - start_time
        metrics = engine.compute_metrics(periods_per_year=self.config.periods_per_year)

        logger.info(
            "Backtest complete: %d ticks in %.2fs | PnL: %.2f | Sharpe: %.2f",
            tick_count, duration,
            metrics.get("total_net_pnl", 0),
            metrics.get("sharpe_ratio", 0),
        )

        return BacktestResult(
            config=self.config,
            metrics=metrics,
            trades=engine.trade_history,
            signals=engine.signals,
            equity_snapshots=trader.equity_snapshots,
            ticks_processed=tick_count,
            duration_seconds=duration,
            engine=engine,
        )

    def _build_feed(self) -> Iterator[dict[str, Any]]:
        """Build the data feed based on config.feed_source."""
        if self.config.feed_source == "database":
            return self._db_feed()
        elif self.config.feed_source == "csv":
            return self._csv_feed()
        elif self.config.feed_source == "synthetic":
            return self._synthetic_feed()
        else:
            raise ValueError(f"Unknown feed source: {self.config.feed_source}")

    def _db_feed(self) -> Iterator[dict[str, Any]]:
        from trading_system.data.feed import db_feed
        return db_feed(
            symbol=self.config.symbol,
            exchange=self.config.exchange,
            timeframe=self.config.timeframe,
            start=self.config.start,
            end=self.config.end,
        )

    def _csv_feed(self) -> Iterator[dict[str, Any]]:
        """Load CSV data and yield as feed dicts."""
        import asyncio
        from trading_system.data.providers.csv_loader import CSVProvider

        if not self.config.csv_path:
            raise ValueError("csv_path is required for CSV feed source")

        provider = CSVProvider(
            file_path=self.config.csv_path,
            symbol=self.config.symbol,
            exchange=self.config.exchange,
            timeframe=self.config.timeframe,
        )

        async def _load():
            start = self.config.start or datetime(2000, 1, 1)
            end = self.config.end or datetime(2100, 1, 1)
            return await provider.fetch_historical(
                self.config.symbol, self.config.timeframe, start, end,
            )

        candles = asyncio.get_event_loop().run_until_complete(_load())
        return (c.to_dict() for c in candles)

    def _synthetic_feed(self) -> Iterator[dict[str, Any]]:
        from trading_system.data.feed import generate_feed
        return generate_feed(
            symbol=self.config.symbol,
            start_price=self.config.synthetic_start_price,
            num_points=self.config.synthetic_points,
            seed=self.config.random_seed,
        )
