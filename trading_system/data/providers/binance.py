"""
Binance data provider — REST + WebSocket for candles, order book,
ticker stats, and book ticker.

Collects all 11 kline fields, order book depth, 24h ticker, and
best bid/ask. Computes derived fields (buy pressure, VWAP, etc.).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import websockets

from trading_system.data.providers.base import BaseProvider, Candle

logger = logging.getLogger(__name__)

BINANCE_REST_BASE = "https://api.binance.com"
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
BINANCE_COMBINED_WS = "wss://stream.binance.com:9443/stream"

TIMEFRAME_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}

MAX_CANDLES_PER_REQUEST = 1000

DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
]


def compute_derived(extra: dict) -> dict:
    """Compute derived trading metrics from raw kline extra fields."""
    volume = extra.get("volume", 0)
    taker_buy_vol = extra.get("taker_buy_base_volume", 0)
    quote_vol = extra.get("quote_volume", 0)
    num_trades = extra.get("num_trades", 0)
    o = extra.get("open", 0)
    h = extra.get("high", 0)
    l = extra.get("low", 0)  # noqa: E741
    c = extra.get("close", 0)

    hl_range = h - l if h != l else 1e-10

    extra["buy_pressure"] = round(taker_buy_vol / volume, 6) if volume else 0
    extra["vwap"] = round(quote_vol / volume, 8) if volume else 0
    extra["volume_per_trade"] = round(volume / num_trades, 8) if num_trades else 0
    extra["body_ratio"] = round(abs(c - o) / hl_range, 6)
    extra["upper_wick_ratio"] = round((h - max(o, c)) / hl_range, 6)
    extra["lower_wick_ratio"] = round((min(o, c) - l) / hl_range, 6)

    return extra


class BinanceProvider(BaseProvider):
    """Binance spot market data provider."""

    name = "binance"

    def __init__(self, api_key: str = "", api_secret: str = "") -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Klines (OHLCV + all extra fields)
    # ------------------------------------------------------------------

    async def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch historical klines from Binance REST API.

        Automatically paginates if the date range exceeds 1000 candles.
        """
        await self._ensure_session()

        interval = TIMEFRAME_MAP.get(timeframe, timeframe)
        all_candles: list[Candle] = []
        current_start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        while current_start_ms < end_ms:
            url = (
                f"{BINANCE_REST_BASE}/api/v3/klines"
                f"?symbol={symbol}"
                f"&interval={interval}"
                f"&startTime={current_start_ms}"
                f"&endTime={end_ms}"
                f"&limit={MAX_CANDLES_PER_REQUEST}"
            )

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Binance API error %d: %s", resp.status, text)
                    break
                raw = await resp.json()

            if not raw:
                break

            for k in raw:
                candle = self._parse_rest_kline(k, symbol, timeframe)
                all_candles.append(candle)

            last_close_time = raw[-1][6]
            current_start_ms = last_close_time + 1

            if len(raw) < MAX_CANDLES_PER_REQUEST:
                break

            await asyncio.sleep(0.1)

        logger.info(
            "Fetched %d candles for %s %s [%s → %s]",
            len(all_candles), symbol, timeframe, start, end,
        )
        return all_candles

    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]:
        """Stream real-time klines via Binance WebSocket.

        Reconnects automatically on disconnection with exponential backoff.
        Only yields candles when the kline is closed (complete).
        """
        interval = TIMEFRAME_MAP.get(timeframe, timeframe)
        stream = f"{symbol.lower()}@kline_{interval}"
        url = f"{BINANCE_WS_BASE}/{stream}"

        backoff = 1
        max_backoff = 60

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info("Connected to Binance WS: %s", stream)
                    backoff = 1

                    async for message in ws:
                        data = json.loads(message)
                        kline = data.get("k", {})

                        if not kline.get("x", False):
                            continue

                        yield self._parse_ws_kline(kline, symbol, timeframe)

            except (
                websockets.ConnectionClosed,
                websockets.InvalidStatusCode,
                ConnectionError,
                OSError,
            ) as exc:
                logger.warning(
                    "Binance WS disconnected (%s), reconnecting in %ds...",
                    exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def stream_candles_multi(
        self,
        symbols: list[str],
        timeframe: str = "1m",
    ) -> AsyncIterator[Candle]:
        """Stream klines for multiple symbols over a single combined WS."""
        interval = TIMEFRAME_MAP.get(timeframe, timeframe)
        streams = [f"{s.lower()}@kline_{interval}" for s in symbols]
        url = f"{BINANCE_COMBINED_WS}?streams={'/'.join(streams)}"

        backoff = 1
        max_backoff = 60

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info("Connected to Binance combined WS: %d symbols", len(symbols))
                    backoff = 1

                    async for message in ws:
                        payload = json.loads(message)
                        data = payload.get("data", {})
                        kline = data.get("k", {})

                        if not kline.get("x", False):
                            continue

                        sym = kline.get("s", "").upper()
                        yield self._parse_ws_kline(kline, sym, timeframe)

            except (
                websockets.ConnectionClosed,
                websockets.InvalidStatusCode,
                ConnectionError,
                OSError,
            ) as exc:
                logger.warning(
                    "Binance combined WS disconnected (%s), reconnecting in %ds...",
                    exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    # ------------------------------------------------------------------
    # Order Book Depth
    # ------------------------------------------------------------------

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Fetch order book depth snapshot. Weight: 5 for limit<=100."""
        await self._ensure_session()

        url = f"{BINANCE_REST_BASE}/api/v3/depth?symbol={symbol}&limit={limit}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("Binance depth error %d: %s", resp.status, text)
                return {}
            data = await resp.json()

        bids = [[float(p), float(q)] for p, q in data.get("bids", [])]
        asks = [[float(p), float(q)] for p, q in data.get("asks", [])]

        total_bid_qty = sum(q for _, q in bids)
        total_ask_qty = sum(q for _, q in asks)
        spread = (asks[0][0] - bids[0][0]) if bids and asks else 0
        mid_price = (asks[0][0] + bids[0][0]) / 2 if bids and asks else 0
        imbalance = round(total_bid_qty / total_ask_qty, 6) if total_ask_qty else 0

        return {
            "symbol": symbol,
            "exchange": "binance",
            "timestamp": datetime.now(tz=timezone.utc),
            "bids": bids,
            "asks": asks,
            "best_bid_price": bids[0][0] if bids else 0,
            "best_bid_qty": bids[0][1] if bids else 0,
            "best_ask_price": asks[0][0] if asks else 0,
            "best_ask_qty": asks[0][1] if asks else 0,
            "spread": round(spread, 8),
            "spread_pct": round(spread / mid_price * 100, 6) if mid_price else 0,
            "mid_price": round(mid_price, 8),
            "total_bid_qty": round(total_bid_qty, 8),
            "total_ask_qty": round(total_ask_qty, 8),
            "book_imbalance": imbalance,
            "last_update_id": data.get("lastUpdateId", 0),
        }

    async def fetch_order_books(
        self,
        symbols: list[str],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch order book snapshots for multiple symbols concurrently."""
        tasks = [self.fetch_order_book(sym, limit) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        snapshots = []
        for r in results:
            if isinstance(r, dict) and r:
                snapshots.append(r)
            elif isinstance(r, Exception):
                logger.error("Order book fetch failed: %s", r)
        return snapshots

    # ------------------------------------------------------------------
    # 24h Ticker Stats
    # ------------------------------------------------------------------

    async def fetch_ticker_24h(self, symbol: str) -> dict[str, Any]:
        """Fetch 24h ticker statistics for a single symbol. Weight: 2."""
        await self._ensure_session()

        url = f"{BINANCE_REST_BASE}/api/v3/ticker/24hr?symbol={symbol}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("Binance ticker error %d: %s", resp.status, text)
                return {}
            data = await resp.json()

        return self._parse_ticker_24h(data)

    async def fetch_tickers_24h(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch 24h ticker stats for multiple symbols concurrently."""
        tasks = [self.fetch_ticker_24h(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tickers = []
        for r in results:
            if isinstance(r, dict) and r:
                tickers.append(r)
            elif isinstance(r, Exception):
                logger.error("Ticker fetch failed: %s", r)
        return tickers

    # ------------------------------------------------------------------
    # Book Ticker (best bid/ask)
    # ------------------------------------------------------------------

    async def fetch_book_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch best bid/ask for a single symbol. Weight: 2."""
        await self._ensure_session()

        url = f"{BINANCE_REST_BASE}/api/v3/ticker/bookTicker?symbol={symbol}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("Binance bookTicker error %d: %s", resp.status, text)
                return {}
            data = await resp.json()

        return {
            "symbol": data["symbol"],
            "exchange": "binance",
            "timestamp": datetime.now(tz=timezone.utc),
            "best_bid_price": float(data["bidPrice"]),
            "best_bid_qty": float(data["bidQty"]),
            "best_ask_price": float(data["askPrice"]),
            "best_ask_qty": float(data["askQty"]),
            "spread": round(float(data["askPrice"]) - float(data["bidPrice"]), 8),
        }

    async def fetch_book_tickers(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch best bid/ask for multiple symbols concurrently."""
        tasks = [self.fetch_book_ticker(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tickers = []
        for r in results:
            if isinstance(r, dict) and r:
                tickers.append(r)
            elif isinstance(r, Exception):
                logger.error("Book ticker fetch failed: %s", r)
        return tickers

    # ------------------------------------------------------------------
    # Combined multi-stream WS (ticker + bookTicker for all symbols)
    # ------------------------------------------------------------------

    async def stream_market_data(
        self,
        symbols: list[str],
        timeframe: str = "1m",
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream klines + ticker + bookTicker for multiple symbols.

        Yields dicts with a 'type' key: 'kline', 'ticker', or 'book_ticker'.
        Consumers should filter by type and persist at their desired interval.
        """
        interval = TIMEFRAME_MAP.get(timeframe, timeframe)
        streams = []
        for s in symbols:
            sl = s.lower()
            streams.append(f"{sl}@kline_{interval}")
            streams.append(f"{sl}@ticker")
            streams.append(f"{sl}@bookTicker")

        url = f"{BINANCE_COMBINED_WS}?streams={'/'.join(streams)}"
        backoff = 1
        max_backoff = 60

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info(
                        "Connected to Binance market data WS: %d symbols, %d streams",
                        len(symbols), len(streams),
                    )
                    backoff = 1

                    async for message in ws:
                        payload = json.loads(message)
                        stream_name = payload.get("stream", "")
                        data = payload.get("data", {})

                        if "@kline_" in stream_name:
                            kline = data.get("k", {})
                            if kline.get("x", False):
                                sym = kline.get("s", "").upper()
                                candle = self._parse_ws_kline(kline, sym, timeframe)
                                yield {"type": "kline", "data": candle}

                        elif "@ticker" in stream_name and "@bookTicker" not in stream_name:
                            yield {
                                "type": "ticker",
                                "data": self._parse_ticker_24h(data),
                            }

                        elif "@bookTicker" in stream_name:
                            yield {
                                "type": "book_ticker",
                                "data": {
                                    "symbol": data.get("s", ""),
                                    "exchange": "binance",
                                    "timestamp": datetime.now(tz=timezone.utc),
                                    "best_bid_price": float(data.get("b", 0)),
                                    "best_bid_qty": float(data.get("B", 0)),
                                    "best_ask_price": float(data.get("a", 0)),
                                    "best_ask_qty": float(data.get("A", 0)),
                                    "spread": round(
                                        float(data.get("a", 0)) - float(data.get("b", 0)),
                                        8,
                                    ),
                                },
                            }

            except (
                websockets.ConnectionClosed,
                websockets.InvalidStatusCode,
                ConnectionError,
                OSError,
            ) as exc:
                logger.warning(
                    "Binance market data WS disconnected (%s), reconnecting in %ds...",
                    exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    # ------------------------------------------------------------------
    # Symbol listing
    # ------------------------------------------------------------------

    async def get_symbols(self) -> list[str]:
        """Fetch all trading pair symbols from Binance exchange info."""
        await self._ensure_session()

        url = f"{BINANCE_REST_BASE}/api/v3/exchangeInfo"
        async with self._session.get(url) as resp:
            data = await resp.json()

        return [s["symbol"] for s in data.get("symbols", []) if s["status"] == "TRADING"]

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_rest_kline(k: list, symbol: str, timeframe: str) -> Candle:
        """Parse a Binance REST kline array into a Candle with all 11 fields."""
        o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])  # noqa: E741
        taker_buy_base = float(k[9])
        taker_buy_quote = float(k[10])
        quote_vol = float(k[7])
        num_trades = int(k[8])

        extra = {
            "close_time": k[6],
            "quote_volume": quote_vol,
            "num_trades": num_trades,
            "taker_buy_base_volume": taker_buy_base,
            "taker_buy_quote_volume": taker_buy_quote,
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        }
        compute_derived(extra)

        return Candle(
            symbol=symbol,
            exchange="binance",
            timeframe=timeframe,
            time=datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
            open=o, high=h, low=l, close=c, volume=v,
            extra=extra,
        )

    @staticmethod
    def _parse_ws_kline(k: dict, symbol: str, timeframe: str) -> Candle:
        """Parse a Binance WebSocket kline event into a Candle with all fields."""
        o, h = float(k["o"]), float(k["h"])
        l, c = float(k["l"]), float(k["c"])  # noqa: E741
        v = float(k["v"])
        taker_buy_base = float(k.get("V", 0))
        taker_buy_quote = float(k.get("Q", 0))
        quote_vol = float(k.get("q", 0))
        num_trades = int(k.get("n", 0))

        extra = {
            "close_time": k.get("T", 0),
            "quote_volume": quote_vol,
            "num_trades": num_trades,
            "taker_buy_base_volume": taker_buy_base,
            "taker_buy_quote_volume": taker_buy_quote,
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        }
        compute_derived(extra)

        return Candle(
            symbol=symbol,
            exchange="binance",
            timeframe=timeframe,
            time=datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc),
            open=o, high=h, low=l, close=c, volume=v,
            extra=extra,
        )

    @staticmethod
    def _parse_ticker_24h(data: dict) -> dict[str, Any]:
        """Parse 24h ticker response (REST or WS) into a normalised dict."""
        return {
            "symbol": data.get("symbol") or data.get("s", ""),
            "exchange": "binance",
            "timestamp": datetime.now(tz=timezone.utc),
            "price_change": float(data.get("priceChange") or data.get("p", 0)),
            "price_change_pct": float(data.get("priceChangePercent") or data.get("P", 0)),
            "weighted_avg_price": float(data.get("weightedAvgPrice") or data.get("w", 0)),
            "prev_close": float(data.get("prevClosePrice") or data.get("x", 0)),
            "last_price": float(data.get("lastPrice") or data.get("c", 0)),
            "volume": float(data.get("volume") or data.get("v", 0)),
            "quote_volume": float(data.get("quoteVolume") or data.get("q", 0)),
            "open_price": float(data.get("openPrice") or data.get("o", 0)),
            "high_price": float(data.get("highPrice") or data.get("h", 0)),
            "low_price": float(data.get("lowPrice") or data.get("l", 0)),
            "trade_count": int(data.get("count") or data.get("n", 0)),
            "open_time": data.get("openTime") or data.get("O", 0),
            "close_time": data.get("closeTime") or data.get("C", 0),
        }
