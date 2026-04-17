"""
Twelve Data provider — REST API for Forex (and stock) OHLCV candles.

Free tier: 800 requests/day, up to 5000 candles per request.
Sign up at https://twelvedata.com for a free API key.

Supports historical backfill and periodic polling.
No WebSocket on free tier, so we poll at intervals.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from trading_system.data.providers.base import BaseProvider, Candle

logger = logging.getLogger(__name__)

TWELVEDATA_BASE = "https://api.twelvedata.com"

TIMEFRAME_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
    "1w": "1week",
}

DEFAULT_FOREX_SYMBOLS = [
    "EUR/USD",
    "USD/JPY",
    "GBP/USD",
    "AUD/USD",
    "USD/CAD",
    "USD/CHF",
    "NZD/USD",
    "EUR/GBP",
    "EUR/JPY",
    "GBP/JPY",
]


class TwelveDataProvider(BaseProvider):
    """Twelve Data provider for Forex OHLCV candles."""

    name = "twelvedata"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch historical OHLCV candles from Twelve Data.

        Uses the /time_series endpoint. Up to 5000 candles per request.
        """
        await self._ensure_session()

        interval = TIMEFRAME_MAP.get(timeframe, timeframe)
        start_str = start.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end.strftime("%Y-%m-%d %H:%M:%S")

        all_candles: list[Candle] = []
        earliest_time = end_str

        while True:
            params = {
                "symbol": symbol,
                "interval": interval,
                "start_date": start_str,
                "end_date": earliest_time,
                "outputsize": 5000,
                "apikey": self._api_key,
                "format": "JSON",
                "timezone": "UTC",
            }

            url = f"{TWELVEDATA_BASE}/time_series"
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Twelve Data API error %d: %s", resp.status, text)
                    break
                data = await resp.json()

            if data.get("status") == "error":
                logger.error("Twelve Data error: %s", data.get("message", ""))
                break

            values = data.get("values", [])
            if not values:
                break

            for v in values:
                candle = self._parse_candle(v, symbol, timeframe)
                if candle:
                    all_candles.append(candle)

            if len(values) < 5000:
                break

            earliest_time = values[-1]["datetime"]
            await asyncio.sleep(0.5)

        all_candles.sort(key=lambda c: c.time)

        seen = set()
        unique = []
        for c in all_candles:
            if c.time not in seen:
                seen.add(c.time)
                unique.append(c)

        logger.info(
            "Fetched %d candles for %s %s [%s → %s]",
            len(unique), symbol, timeframe, start, end,
        )
        return unique

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 1,
    ) -> list[Candle]:
        """Fetch the most recent N candles. Uses 1 API credit."""
        await self._ensure_session()

        interval = TIMEFRAME_MAP.get(timeframe, timeframe)
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": count,
            "apikey": self._api_key,
            "format": "JSON",
            "timezone": "UTC",
        }

        url = f"{TWELVEDATA_BASE}/time_series"
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("Twelve Data API error %d: %s", resp.status, text)
                return []
            data = await resp.json()

        if data.get("status") == "error":
            logger.error("Twelve Data error: %s", data.get("message", ""))
            return []

        candles = []
        for v in data.get("values", []):
            candle = self._parse_candle(v, symbol, timeframe)
            if candle:
                candles.append(candle)

        candles.sort(key=lambda c: c.time)
        return candles

    async def fetch_quote(self, symbol: str) -> dict:
        """Fetch real-time quote (price snapshot). Uses 1 API credit."""
        await self._ensure_session()

        params = {
            "symbol": symbol,
            "apikey": self._api_key,
        }

        url = f"{TWELVEDATA_BASE}/quote"
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()

        if data.get("status") == "error":
            return {}

        return {
            "symbol": data.get("symbol", symbol),
            "exchange": "twelvedata",
            "timestamp": datetime.now(tz=timezone.utc),
            "open_price": float(data.get("open", 0)),
            "high_price": float(data.get("high", 0)),
            "low_price": float(data.get("low", 0)),
            "close_price": float(data.get("close", 0)),
            "prev_close": float(data.get("previous_close", 0)),
            "price_change": float(data.get("change", 0)),
            "price_change_pct": float(data.get("percent_change", 0)),
            "volume": float(data.get("volume", 0) or 0),
        }

    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Poll for new candles at regular intervals.

        Free tier doesn't have WebSocket, so we poll every interval.
        """
        interval_seconds = self._timeframe_to_seconds(timeframe)
        poll_delay = max(interval_seconds, 60)

        while True:
            try:
                candles = await self.fetch_latest(symbol, timeframe, count=1)
                if candles:
                    yield candles[0]
            except Exception as exc:
                logger.error("Twelve Data poll error for %s: %s", symbol, exc)

            await asyncio.sleep(poll_delay)

    async def get_symbols(self) -> list[str]:
        """Return available forex symbols from Twelve Data."""
        await self._ensure_session()

        params = {
            "type": "Forex",
            "apikey": self._api_key,
        }

        url = f"{TWELVEDATA_BASE}/forex_pairs"
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return DEFAULT_FOREX_SYMBOLS
            data = await resp.json()

        pairs = data.get("data", [])
        return [p["symbol"] for p in pairs[:100]]

    @staticmethod
    def _parse_candle(v: dict, symbol: str, timeframe: str) -> Candle | None:
        """Parse a Twelve Data time_series value into a Candle."""
        try:
            dt_str = v.get("datetime", "")
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )

            o = float(v.get("open", 0))
            h = float(v.get("high", 0))
            l = float(v.get("low", 0))  # noqa: E741
            c = float(v.get("close", 0))
            vol = float(v.get("volume", 0) or 0)

            hl_range = h - l if h != l else 1e-10

            extra = {
                "open": o, "high": h, "low": l, "close": c, "volume": vol,
                "body_ratio": round(abs(c - o) / hl_range, 6),
                "upper_wick_ratio": round((h - max(o, c)) / hl_range, 6),
                "lower_wick_ratio": round((min(o, c) - l) / hl_range, 6),
            }

            return Candle(
                symbol=symbol,
                exchange="twelvedata",
                timeframe=timeframe,
                time=dt,
                open=o, high=h, low=l, close=c,
                volume=vol,
                extra=extra,
            )
        except (ValueError, TypeError) as exc:
            logger.warning("Failed to parse candle for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> int:
        mapping = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
        }
        return mapping.get(timeframe, 300)
