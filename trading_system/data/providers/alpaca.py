"""
Alpaca data provider — REST for historical bars, WebSocket for live streaming.

Supports both paper and live environments via ALPACA_BASE_URL.
Uses the alpaca-py SDK for REST and raw websockets for streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import AsyncIterator

import websockets

from trading_system.data.providers.base import BaseProvider, Candle

logger = logging.getLogger(__name__)

ALPACA_DATA_REST = "https://data.alpaca.markets"
ALPACA_DATA_WS = "wss://stream.data.alpaca.markets/v2/iex"

TIMEFRAME_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "4h": "4Hour",
    "1d": "1Day",
    "1w": "1Week",
}

MAX_BARS_PER_REQUEST = 10000


class AlpacaProvider(BaseProvider):
    """Alpaca Markets data provider for US stocks."""

    name = "alpaca"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "APCA-API-KEY-ID": self._api_key,
                    "APCA-API-SECRET-KEY": self._api_secret,
                }
            )

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
        """Fetch historical bars from Alpaca Data API v2.

        Automatically paginates using the next_page_token.
        """
        await self._ensure_session()

        tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        all_candles: list[Candle] = []
        page_token = None

        while True:
            url = (
                f"{ALPACA_DATA_REST}/v2/stocks/{symbol}/bars"
                f"?timeframe={tf}"
                f"&start={start.isoformat()}"
                f"&end={end.isoformat()}"
                f"&limit={MAX_BARS_PER_REQUEST}"
                f"&adjustment=split"
            )
            if page_token:
                url += f"&page_token={page_token}"

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Alpaca API error %d: %s", resp.status, text)
                    break
                data = await resp.json()

            bars = data.get("bars", [])
            if not bars:
                break

            for bar in bars:
                candle = self._parse_bar(bar, symbol, timeframe)
                all_candles.append(candle)

            page_token = data.get("next_page_token")
            if not page_token:
                break

            await asyncio.sleep(0.1)

        logger.info(
            "Fetched %d bars for %s %s [%s → %s]",
            len(all_candles), symbol, timeframe, start, end,
        )
        return all_candles

    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Stream real-time bars via Alpaca WebSocket.

        Reconnects automatically on disconnection with exponential backoff.
        Note: Alpaca streams minute bars; higher timeframes need aggregation.
        """
        backoff = 1
        max_backoff = 60

        while True:
            try:
                async with websockets.connect(ALPACA_DATA_WS) as ws:
                    # Authenticate
                    auth_msg = {
                        "action": "auth",
                        "key": self._api_key,
                        "secret": self._api_secret,
                    }
                    await ws.send(json.dumps(auth_msg))
                    auth_resp = await ws.recv()
                    logger.info("Alpaca WS auth response: %s", auth_resp)

                    # Subscribe to bars
                    sub_msg = {
                        "action": "subscribe",
                        "bars": [symbol],
                    }
                    await ws.send(json.dumps(sub_msg))
                    sub_resp = await ws.recv()
                    logger.info("Alpaca WS subscribe response: %s", sub_resp)

                    backoff = 1

                    async for message in ws:
                        events = json.loads(message)
                        for event in events:
                            if event.get("T") != "b":
                                continue
                            yield self._parse_ws_bar(event, symbol, timeframe)

            except (
                websockets.ConnectionClosed,
                websockets.InvalidStatusCode,
                ConnectionError,
                OSError,
            ) as exc:
                logger.warning(
                    "Alpaca WS disconnected (%s), reconnecting in %ds...",
                    exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def get_symbols(self) -> list[str]:
        """Fetch tradeable stock symbols from Alpaca."""
        await self._ensure_session()

        base_url = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        url = f"{base_url}/v2/assets?status=active&asset_class=us_equity"

        async with self._session.get(url) as resp:
            data = await resp.json()

        return [
            asset["symbol"]
            for asset in data
            if asset.get("tradable", False)
        ]

    @staticmethod
    def _parse_bar(bar: dict, symbol: str, timeframe: str) -> Candle:
        """Parse an Alpaca REST bar into a Candle."""
        return Candle(
            symbol=symbol,
            exchange="alpaca",
            timeframe=timeframe,
            time=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
            open=float(bar["o"]),
            high=float(bar["h"]),
            low=float(bar["l"]),
            close=float(bar["c"]),
            volume=float(bar["v"]),
            extra={"vwap": bar.get("vw"), "trade_count": bar.get("n")},
        )

    @staticmethod
    def _parse_ws_bar(bar: dict, symbol: str, timeframe: str) -> Candle:
        """Parse an Alpaca WebSocket bar event into a Candle."""
        return Candle(
            symbol=bar.get("S", symbol),
            exchange="alpaca",
            timeframe=timeframe,
            time=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
            open=float(bar["o"]),
            high=float(bar["h"]),
            low=float(bar["l"]),
            close=float(bar["c"]),
            volume=float(bar["v"]),
            extra={"vwap": bar.get("vw"), "trade_count": bar.get("n")},
        )
