"""
Finnhub provider — REST API for US stock OHLCV candles.

Free tier: 60 API calls/minute (~86,400/day). No credit card required.
Sign up at https://finnhub.io for a free API key.

Supports historical backfill and periodic polling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from trading_system.data.providers.base import BaseProvider, Candle

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"

RESOLUTION_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "1d": "D",
    "1w": "W",
}

DEFAULT_STOCK_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "JPM", "V", "AVGO",
]


class FinnhubProvider(BaseProvider):
    """Finnhub provider for US stock OHLCV candles."""

    name = "finnhub"

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
        """Fetch historical OHLCV candles from Finnhub.

        Finnhub returns arrays of o/h/l/c/v/t values.
        Free tier supports up to 1 year of 1-min data.
        """
        await self._ensure_session()

        resolution = RESOLUTION_MAP.get(timeframe, "5")
        from_ts = int(start.timestamp())
        to_ts = int(end.timestamp())

        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": from_ts,
            "to": to_ts,
            "token": self._api_key,
        }

        url = f"{FINNHUB_BASE}/stock/candle"
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("Finnhub API error %d: %s", resp.status, text)
                return []
            data = await resp.json()

        if data.get("s") != "ok":
            logger.warning("Finnhub returned status=%s for %s", data.get("s"), symbol)
            return []

        candles = self._parse_candle_arrays(data, symbol, timeframe)

        logger.info(
            "Fetched %d candles for %s %s [%s -> %s]",
            len(candles), symbol, timeframe, start, end,
        )
        return candles

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 1,
    ) -> list[Candle]:
        """Fetch the most recent N candles.

        Finnhub doesn't have a 'latest N' param, so we compute the
        time window from the timeframe and count.
        """
        await self._ensure_session()

        seconds_per_candle = self._timeframe_to_seconds(timeframe)
        now = datetime.now(tz=timezone.utc)
        buffer = max(count * 3, 10)
        from_dt = datetime.fromtimestamp(
            now.timestamp() - seconds_per_candle * buffer,
            tz=timezone.utc,
        )

        candles = await self.fetch_historical(symbol, timeframe, from_dt, now)
        return candles[-count:] if len(candles) > count else candles

    async def fetch_quote(self, symbol: str) -> dict:
        """Fetch real-time quote for a stock."""
        await self._ensure_session()

        params = {"symbol": symbol, "token": self._api_key}
        url = f"{FINNHUB_BASE}/quote"

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()

        if not data or not data.get("c"):
            return {}

        return {
            "symbol": symbol,
            "exchange": "finnhub",
            "timestamp": datetime.fromtimestamp(data.get("t", 0), tz=timezone.utc),
            "current_price": float(data.get("c", 0)),
            "open_price": float(data.get("o", 0)),
            "high_price": float(data.get("h", 0)),
            "low_price": float(data.get("l", 0)),
            "prev_close": float(data.get("pc", 0)),
            "price_change": float(data.get("d", 0)),
            "price_change_pct": float(data.get("dp", 0)),
        }

    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Poll for new candles at regular intervals.

        Finnhub free WebSocket gives trades, not candles,
        so we poll the REST API instead.
        """
        interval_seconds = self._timeframe_to_seconds(timeframe)
        poll_delay = max(interval_seconds, 60)

        while True:
            try:
                candles = await self.fetch_latest(symbol, timeframe, count=1)
                if candles:
                    yield candles[0]
            except Exception as exc:
                logger.error("Finnhub poll error for %s: %s", symbol, exc)

            await asyncio.sleep(poll_delay)

    async def get_symbols(self) -> list[str]:
        """Return available US stock symbols."""
        await self._ensure_session()

        params = {"exchange": "US", "token": self._api_key}
        url = f"{FINNHUB_BASE}/stock/symbol"

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return DEFAULT_STOCK_SYMBOLS
            data = await resp.json()

        return [s["symbol"] for s in data[:100] if s.get("type") == "Common Stock"]

    def _parse_candle_arrays(
        self, data: dict, symbol: str, timeframe: str
    ) -> list[Candle]:
        """Parse Finnhub's array-based candle response into Candle objects."""
        opens = data.get("o", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        closes = data.get("c", [])
        volumes = data.get("v", [])
        timestamps = data.get("t", [])

        candles = []
        for i in range(len(timestamps)):
            try:
                o = float(opens[i])
                h = float(highs[i])
                l = float(lows[i])  # noqa: E741
                c = float(closes[i])
                v = float(volumes[i])
                dt = datetime.fromtimestamp(timestamps[i], tz=timezone.utc)

                hl_range = h - l if h != l else 1e-10

                extra = {
                    "open": o, "high": h, "low": l, "close": c, "volume": v,
                    "body_ratio": round(abs(c - o) / hl_range, 6),
                    "upper_wick_ratio": round((h - max(o, c)) / hl_range, 6),
                    "lower_wick_ratio": round((min(o, c) - l) / hl_range, 6),
                }

                candles.append(Candle(
                    symbol=symbol,
                    exchange="finnhub",
                    timeframe=timeframe,
                    time=dt,
                    open=o, high=h, low=l, close=c,
                    volume=v,
                    extra=extra,
                ))
            except (ValueError, TypeError, IndexError) as exc:
                logger.warning("Failed to parse candle %d for %s: %s", i, symbol, exc)

        return candles

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> int:
        mapping = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
        }
        return mapping.get(timeframe, 300)
