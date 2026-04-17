"""
Polygon.io provider — REST API for US stock OHLCV candles with
VWAP and trade count, plus NBBO (bid/ask) quotes.

Free tier: 5 API calls/minute, historical minute bars available.
Sign up at https://polygon.io for a free API key (no credit card).

Key advantage over Finnhub: every candle bar includes VWAP and
number-of-trades, which enables computing volume_per_trade and
approximating buy pressure from price action.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from trading_system.data.providers.base import BaseProvider, Candle

logger = logging.getLogger(__name__)

POLYGON_BASE = "https://api.polygon.io"

TIMESPAN_MAP = {
    "1m": ("1", "minute"),
    "5m": ("5", "minute"),
    "15m": ("15", "minute"),
    "30m": ("30", "minute"),
    "1h": ("1", "hour"),
    "4h": ("4", "hour"),
    "1d": ("1", "day"),
    "1w": ("1", "week"),
}

DEFAULT_STOCK_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "JPM", "V", "AVGO",
]


class PolygonProvider(BaseProvider):
    """Polygon.io provider for US stock OHLCV + VWAP + trade count."""

    name = "polygon"

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

    async def _rate_limit_pause(self):
        """Polygon free tier: 5 calls/min → wait ~12.5s between calls."""
        await asyncio.sleep(12.5)

    async def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch historical OHLCV+VWAP+N candles from Polygon aggregates.

        Endpoint: /v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}
        Each bar includes: v (vol), vw (VWAP), o, h, l, c, t (ms), n (trades).
        """
        await self._ensure_session()

        mult, timespan = TIMESPAN_MAP.get(timeframe, ("1", "minute"))
        from_ms = int(start.timestamp() * 1000)
        to_ms = int(end.timestamp() * 1000)

        all_candles: list[Candle] = []
        cursor_from = from_ms

        while cursor_from < to_ms:
            url = (
                f"{POLYGON_BASE}/v2/aggs/ticker/{symbol}"
                f"/range/{mult}/{timespan}/{cursor_from}/{to_ms}"
            )
            params = {
                "adjusted": "true",
                "sort": "asc",
                "limit": 50000,
                "apiKey": self._api_key,
            }

            async with self._session.get(url, params=params) as resp:
                if resp.status == 429:
                    logger.warning("Polygon rate limited, waiting 60s…")
                    await asyncio.sleep(60)
                    continue
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Polygon API error %d: %s", resp.status, text)
                    break
                data = await resp.json()

            results = data.get("results", [])
            if not results:
                break

            for bar in results:
                candle = self._parse_bar(bar, symbol, timeframe)
                if candle:
                    all_candles.append(candle)

            if len(results) < 50000:
                break

            cursor_from = results[-1].get("t", to_ms) + 1
            await self._rate_limit_pause()

        seen = set()
        unique = []
        for c in all_candles:
            if c.time not in seen:
                seen.add(c.time)
                unique.append(c)

        logger.info(
            "Fetched %d candles for %s %s [%s -> %s]",
            len(unique), symbol, timeframe, start, end,
        )
        return unique

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 1,
    ) -> list[Candle]:
        """Fetch the most recent N candles."""
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

    async def fetch_nbbo(self, symbol: str) -> dict | None:
        """Fetch the latest NBBO (National Best Bid and Offer) quote.

        Returns bid/ask price+size and spread.
        Endpoint: /v3/quotes/{ticker}?limit=1&sort=timestamp&order=desc
        """
        await self._ensure_session()

        url = f"{POLYGON_BASE}/v3/quotes/{symbol}"
        params = {
            "limit": 1,
            "sort": "timestamp",
            "order": "desc",
            "apiKey": self._api_key,
        }

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("Polygon NBBO error %d: %s", resp.status, text)
                return None
            data = await resp.json()

        results = data.get("results", [])
        if not results:
            return None

        q = results[0]
        bid = float(q.get("bid_price", 0))
        ask = float(q.get("ask_price", 0))

        return {
            "symbol": symbol,
            "exchange": "polygon",
            "timestamp": datetime.now(tz=timezone.utc),
            "bid_price": bid,
            "bid_qty": float(q.get("bid_size", 0)),
            "ask_price": ask,
            "ask_qty": float(q.get("ask_size", 0)),
            "spread": round(ask - bid, 6) if ask and bid else 0,
        }

    async def fetch_nbbo_batch(self, symbols: list[str]) -> list[dict]:
        """Fetch NBBO for multiple symbols (respects rate limits)."""
        results = []
        for sym in symbols:
            try:
                nbbo = await self.fetch_nbbo(sym)
                if nbbo:
                    results.append(nbbo)
            except Exception as exc:
                logger.error("NBBO fetch failed for %s: %s", sym, exc)
            await asyncio.sleep(12.5)
        return results

    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Poll for new candles at regular intervals.

        Polygon free tier has no WebSocket, so we poll.
        With 5 calls/min limit, we batch poll all symbols then wait.
        """
        interval_seconds = max(self._timeframe_to_seconds(timeframe), 60)

        while True:
            try:
                candles = await self.fetch_latest(symbol, timeframe, count=1)
                if candles:
                    yield candles[0]
            except Exception as exc:
                logger.error("Polygon poll error for %s: %s", symbol, exc)

            await asyncio.sleep(interval_seconds)

    async def get_symbols(self) -> list[str]:
        """Return default stock symbols."""
        return DEFAULT_STOCK_SYMBOLS

    def _parse_bar(self, bar: dict, symbol: str, timeframe: str) -> Candle | None:
        """Parse a Polygon aggregate bar into a Candle.

        Bar fields: v (volume), vw (VWAP), o, h, l, c, t (ms), n (trades).
        """
        try:
            o = float(bar.get("o", 0))
            h = float(bar.get("h", 0))
            l = float(bar.get("l", 0))  # noqa: E741
            c = float(bar.get("c", 0))
            v = float(bar.get("v", 0))
            vwap = float(bar.get("vw", 0))
            num_trades = int(bar.get("n", 0))
            ts_ms = bar.get("t", 0)

            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            hl_range = h - l if h != l else 1e-10

            extra = {
                "open": o, "high": h, "low": l, "close": c, "volume": v,
                "vwap": vwap,
                "num_trades": num_trades,
                "volume_per_trade": round(v / num_trades, 8) if num_trades else 0,
                "body_ratio": round(abs(c - o) / hl_range, 6),
                "upper_wick_ratio": round((h - max(o, c)) / hl_range, 6),
                "lower_wick_ratio": round((min(o, c) - l) / hl_range, 6),
            }

            return Candle(
                symbol=symbol,
                exchange="polygon",
                timeframe=timeframe,
                time=dt,
                open=o, high=h, low=l, close=c,
                volume=v,
                extra=extra,
            )
        except (ValueError, TypeError) as exc:
            logger.warning("Failed to parse bar for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> int:
        mapping = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
        }
        return mapping.get(timeframe, 300)
