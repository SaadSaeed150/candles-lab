"""
Abstract base for all exchange / data providers.

Every provider must implement methods for fetching historical candles
and streaming real-time data. The engine and ingestion tasks depend
only on this interface, so swapping providers requires zero changes
to downstream code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator


@dataclass(frozen=True)
class Candle:
    """Normalised OHLCV candle shared across all providers."""

    symbol: str
    exchange: str
    timeframe: str
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "time": self.time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "extra": self.extra,
        }


class BaseProvider(ABC):
    """Contract every data provider must fulfil."""

    name: str = "base"

    @abstractmethod
    async def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch historical candles for the given range.

        Returns a list of Candle objects sorted by time ascending.
        """
        ...

    @abstractmethod
    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Yield candles in real-time as they arrive from the exchange.

        This is a long-running async generator. It should handle
        reconnections internally.
        """
        ...

    @abstractmethod
    async def get_symbols(self) -> list[str]:
        """Return a list of available trading symbols."""
        ...

    async def close(self) -> None:
        """Clean up connections. Override if needed."""
        pass
