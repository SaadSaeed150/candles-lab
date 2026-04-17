"""
Data feeds — provide candle data to the trading engine.

Three feed types:
    generate_feed()     — synthetic random-walk candles (testing/demo)
    db_feed()           — candles from the database (backtesting)
    db_feed_queryset()  — candles from a pre-built QuerySet
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Iterator


def generate_feed(
    symbol: str = "BTCUSDT",
    start_price: float = 105.0,
    num_points: int = 50,
    start_time: datetime | None = None,
    interval: timedelta = timedelta(minutes=1),
    volatility: float = 3.0,
    seed: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield synthetic OHLCV candles with a random-walk price model.

    Args:
        symbol:      Ticker / pair name.
        start_price: Initial close price.
        num_points:  How many candles to generate.
        start_time:  Timestamp of the first candle (defaults to now).
        interval:    Time between candles.
        volatility:  Max absolute price change per candle.
        seed:        Random seed for reproducible data. None uses global random.
    """
    rng = random.Random(seed)
    current_time = start_time or datetime.utcnow()
    price = start_price

    for _ in range(num_points):
        delta = rng.uniform(-volatility, volatility)
        open_price = price
        close_price = max(0.01, price + delta)
        high = max(open_price, close_price) + rng.uniform(0, volatility * 0.5)
        low = min(open_price, close_price) - rng.uniform(0, volatility * 0.5)
        low = max(0.01, low)
        volume = rng.randint(100, 5000)

        yield {
            "symbol": symbol,
            "time": current_time.isoformat(),
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_price, 2),
            "volume": volume,
            "extra": {},
        }

        price = close_price
        current_time += interval


def db_feed(
    symbol: str,
    exchange: str = "binance",
    timeframe: str = "1m",
    start: datetime | None = None,
    end: datetime | None = None,
    batch_size: int = 1000,
) -> Iterator[dict[str, Any]]:
    """Yield candles from the MarketData table.

    Fetches in batches to keep memory usage low on large datasets.
    This is the primary feed for backtesting against real historical data.

    Args:
        symbol:     Trading pair / ticker.
        exchange:   Exchange name filter.
        timeframe:  Timeframe filter.
        start:      Start of date range (inclusive).
        end:        End of date range (inclusive).
        batch_size: Number of rows to fetch per DB query.
    """
    from trading_system.data.models import MarketData

    qs = MarketData.objects.filter(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
    ).order_by("time")

    if start:
        qs = qs.filter(time__gte=start)
    if end:
        qs = qs.filter(time__lte=end)

    for candle in qs.iterator(chunk_size=batch_size):
        yield candle.to_feed_dict()


def db_feed_queryset(queryset, batch_size: int = 1000) -> Iterator[dict[str, Any]]:
    """Yield candles from an arbitrary MarketData QuerySet.

    Useful when you need custom filtering beyond what db_feed provides.
    """
    for candle in queryset.order_by("time").iterator(chunk_size=batch_size):
        yield candle.to_feed_dict()
