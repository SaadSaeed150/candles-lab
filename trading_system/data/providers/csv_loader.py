"""
CSV data provider — loads historical OHLCV data from CSV files.

Supports common CSV formats from TradingView, Binance exports,
Yahoo Finance, and custom formats with configurable column mapping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import pandas as pd

from trading_system.data.providers.base import BaseProvider, Candle

logger = logging.getLogger(__name__)

DEFAULT_COLUMN_MAP = {
    "time": "time",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
}

# Common alternative column names found in CSV exports
COLUMN_ALIASES = {
    "time": ["time", "date", "datetime", "timestamp", "Date", "Datetime", "Timestamp", "Open time"],
    "open": ["open", "Open", "open_price"],
    "high": ["high", "High", "high_price"],
    "low": ["low", "Low", "low_price"],
    "close": ["close", "Close", "close_price", "Adj Close"],
    "volume": ["volume", "Volume", "vol", "Vol"],
}


class CSVProvider(BaseProvider):
    """Load candles from local CSV files.

    Args:
        file_path:    Path to the CSV file.
        symbol:       Symbol name to tag the candles with.
        exchange:     Exchange name (defaults to "manual").
        timeframe:    Timeframe of the data (e.g. "1m", "1d").
        column_map:   Custom column name mapping if the CSV has
                      non-standard headers.
    """

    name = "csv"

    def __init__(
        self,
        file_path: str | Path,
        symbol: str = "UNKNOWN",
        exchange: str = "manual",
        timeframe: str = "1d",
        column_map: dict[str, str] | None = None,
    ) -> None:
        self._file_path = Path(file_path)
        self._symbol = symbol
        self._exchange = exchange
        self._timeframe = timeframe
        self._column_map = column_map or {}
        self._df: pd.DataFrame | None = None

    def _resolve_column(self, canonical: str, df_columns: list[str]) -> str:
        """Find the actual column name in the DataFrame for a canonical name."""
        if canonical in self._column_map:
            return self._column_map[canonical]

        for alias in COLUMN_ALIASES.get(canonical, []):
            if alias in df_columns:
                return alias

        raise ValueError(
            f"Cannot find column for '{canonical}' in CSV. "
            f"Available columns: {df_columns}. "
            f"Pass a column_map to specify the mapping."
        )

    def _load(self) -> pd.DataFrame:
        """Load and normalize the CSV into a standard DataFrame."""
        if self._df is not None:
            return self._df

        if not self._file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self._file_path}")

        df = pd.read_csv(self._file_path)
        cols = list(df.columns)

        col_map = {}
        for canonical in ["time", "open", "high", "low", "close", "volume"]:
            col_map[canonical] = self._resolve_column(canonical, cols)

        df = df.rename(columns={v: k for k, v in col_map.items()})
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        self._df = df
        logger.info("Loaded %d candles from %s", len(df), self._file_path)
        return df

    async def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Return candles from the CSV within the given date range."""
        df = self._load()

        start_utc = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
        end_utc = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end

        mask = (df["time"] >= start_utc) & (df["time"] <= end_utc)
        filtered = df[mask]

        candles = [
            Candle(
                symbol=self._symbol,
                exchange=self._exchange,
                timeframe=self._timeframe,
                time=row["time"].to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for _, row in filtered.iterrows()
        ]

        logger.info(
            "Filtered %d candles from CSV [%s → %s]",
            len(candles), start_utc, end_utc,
        )
        return candles

    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Replay CSV candles as a stream (useful for backtesting simulation).

        Yields one candle at a time with no delay — the consumer
        controls the pace.
        """
        df = self._load()

        for _, row in df.iterrows():
            yield Candle(
                symbol=self._symbol,
                exchange=self._exchange,
                timeframe=self._timeframe,
                time=row["time"].to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )

    async def get_symbols(self) -> list[str]:
        """CSV has a single symbol."""
        return [self._symbol]
