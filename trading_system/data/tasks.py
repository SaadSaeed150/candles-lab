"""
Celery tasks for market data ingestion.

- backfill_historical:       Fetch and store historical candles for a symbol.
- start_live_stream:         Connect to an exchange WebSocket and persist
                             incoming candles in real-time.
- start_market_data_stream:  Combined WS for klines + ticker + bookTicker
                             for all configured symbols (1 min persistence).
- collect_order_books:       Periodic REST fetch of order book depth.
- collect_tickers:           Periodic REST fetch of 24h ticker stats.
- collect_book_tickers:      Periodic REST fetch of best bid/ask.
- ingest_csv:                Import candles from a CSV file.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings as django_settings
from django.utils import timezone as tz

from trading_system.data.models import (
    BookTickerSnapshot,
    MarketData,
    OrderBookSnapshot,
    TickerSnapshot,
)

logger = logging.getLogger(__name__)


def _get_symbols() -> list[str]:
    return getattr(django_settings, "TRADING_SYMBOLS", [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    ])


def _save_candles(candles, batch_size: int = 500) -> int:
    """Bulk-upsert candles into the database, skipping duplicates."""
    objects = [
        MarketData(
            symbol=c.symbol,
            exchange=c.exchange,
            timeframe=c.timeframe,
            time=c.time,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
            extra=c.extra,
        )
        for c in candles
    ]

    created = 0
    for i in range(0, len(objects), batch_size):
        batch = objects[i : i + batch_size]
        result = MarketData.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=["symbol", "exchange", "timeframe", "time"],
            update_fields=["open", "high", "low", "close", "volume", "extra"],
        )
        created += len(result)

    return created


def _save_order_book(data: dict) -> None:
    """Persist a single order book snapshot."""
    OrderBookSnapshot.objects.create(
        symbol=data["symbol"],
        exchange=data["exchange"],
        timestamp=data["timestamp"],
        bids=data["bids"],
        asks=data["asks"],
        best_bid_price=data["best_bid_price"],
        best_bid_qty=data["best_bid_qty"],
        best_ask_price=data["best_ask_price"],
        best_ask_qty=data["best_ask_qty"],
        spread=data["spread"],
        spread_pct=data["spread_pct"],
        mid_price=data["mid_price"],
        total_bid_qty=data["total_bid_qty"],
        total_ask_qty=data["total_ask_qty"],
        book_imbalance=data["book_imbalance"],
        last_update_id=data["last_update_id"],
    )


def _save_ticker(data: dict) -> None:
    """Persist a single 24h ticker snapshot."""
    TickerSnapshot.objects.create(
        symbol=data["symbol"],
        exchange=data["exchange"],
        timestamp=data["timestamp"],
        price_change=data["price_change"],
        price_change_pct=data["price_change_pct"],
        weighted_avg_price=data["weighted_avg_price"],
        prev_close=data["prev_close"],
        last_price=data["last_price"],
        volume=data["volume"],
        quote_volume=data["quote_volume"],
        open_price=data["open_price"],
        high_price=data["high_price"],
        low_price=data["low_price"],
        trade_count=data["trade_count"],
    )


def _save_book_ticker(data: dict) -> None:
    """Persist a single book ticker snapshot."""
    BookTickerSnapshot.objects.create(
        symbol=data["symbol"],
        exchange=data["exchange"],
        timestamp=data["timestamp"],
        best_bid_price=data["best_bid_price"],
        best_bid_qty=data["best_bid_qty"],
        best_ask_price=data["best_ask_price"],
        best_ask_qty=data["best_ask_qty"],
        spread=data["spread"],
    )


def _get_forex_symbols() -> list[str]:
    return getattr(django_settings, "FOREX_SYMBOLS", [
        "EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD",
        "USD/CHF", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY",
    ])


def _get_stock_symbols() -> list[str]:
    return getattr(django_settings, "STOCK_SYMBOLS", [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
        "META", "TSLA", "JPM", "V", "AVGO",
    ])


def _get_provider(exchange: str, **kwargs):
    """Instantiate the correct provider for the given exchange."""
    if exchange == "binance":
        from trading_system.data.providers.binance import BinanceProvider
        return BinanceProvider(
            api_key=kwargs.get("api_key", ""),
            api_secret=kwargs.get("api_secret", ""),
        )
    elif exchange == "twelvedata":
        from trading_system.data.providers.twelvedata import TwelveDataProvider
        api_key = kwargs.get("api_key", "") or getattr(
            django_settings, "TWELVEDATA_API_KEY", ""
        )
        return TwelveDataProvider(api_key=api_key)
    elif exchange == "polygon":
        from trading_system.data.providers.polygon import PolygonProvider
        api_key = kwargs.get("api_key", "") or getattr(
            django_settings, "POLYGON_API_KEY", ""
        )
        return PolygonProvider(api_key=api_key)
    elif exchange == "finnhub":
        from trading_system.data.providers.finnhub import FinnhubProvider
        api_key = kwargs.get("api_key", "") or getattr(
            django_settings, "FINNHUB_API_KEY", ""
        )
        return FinnhubProvider(api_key=api_key)
    elif exchange == "alpaca":
        from trading_system.data.providers.alpaca import AlpacaProvider
        return AlpacaProvider(
            api_key=kwargs.get("api_key", ""),
            api_secret=kwargs.get("api_secret", ""),
        )
    else:
        raise ValueError(f"Unknown exchange: {exchange}")


def _get_or_create_event_loop():
    """Get existing event loop or create a new one."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


# ------------------------------------------------------------------
# Existing tasks (updated)
# ------------------------------------------------------------------

@shared_task(bind=True, name="data.backfill_historical")
def backfill_historical(
    self,
    symbol: str,
    exchange: str,
    timeframe: str,
    start_iso: str,
    end_iso: str,
    api_key: str = "",
    api_secret: str = "",
) -> dict:
    """Fetch historical candles and store them in the database."""
    start = datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc)

    provider = _get_provider(exchange, api_key=api_key, api_secret=api_secret)
    loop = _get_or_create_event_loop()

    async def _run():
        try:
            return await provider.fetch_historical(symbol, timeframe, start, end)
        finally:
            await provider.close()

    candles = loop.run_until_complete(_run())
    saved = _save_candles(candles)

    logger.info(
        "Backfill complete: %s %s %s [%s → %s] — %d candles saved",
        exchange, symbol, timeframe, start_iso, end_iso, saved,
    )
    return {
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "candles_fetched": len(candles),
        "candles_saved": saved,
    }


@shared_task(bind=True, name="data.backfill_all_symbols")
def backfill_all_symbols(
    self,
    timeframe: str = "1m",
    start_iso: str = "",
    end_iso: str = "",
    exchange: str = "binance",
) -> dict:
    """Backfill historical klines for all configured symbols."""
    symbols = _get_symbols()
    if not start_iso:
        start_iso = (datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )).isoformat()
    if not end_iso:
        end_iso = datetime.now(tz=timezone.utc).isoformat()

    results = {}
    for sym in symbols:
        try:
            result = backfill_historical(
                sym, exchange, timeframe, start_iso, end_iso,
            )
            results[sym] = result
        except Exception as exc:
            logger.error("Backfill failed for %s: %s", sym, exc)
            results[sym] = {"error": str(exc)}

    return results


@shared_task(bind=True, name="data.start_live_stream")
def start_live_stream(
    self,
    symbol: str,
    exchange: str,
    timeframe: str = "1m",
    api_key: str = "",
    api_secret: str = "",
    max_candles: int = 0,
) -> dict:
    """Connect to exchange WebSocket and persist candles as they arrive."""
    provider = _get_provider(exchange, api_key=api_key, api_secret=api_secret)
    channel_layer = get_channel_layer()
    group_name = f"market_{symbol}"
    loop = _get_or_create_event_loop()

    count = 0

    async def _stream():
        nonlocal count
        try:
            async for candle in provider.stream_candles(symbol, timeframe):
                _save_candles([candle])

                if channel_layer:
                    await channel_layer.group_send(
                        group_name,
                        {
                            "type": "market_update",
                            "data": candle.to_dict(),
                        },
                    )

                count += 1
                if max_candles and count >= max_candles:
                    logger.info("Reached max_candles=%d, stopping stream.", max_candles)
                    break
        finally:
            await provider.close()

    loop.run_until_complete(_stream())

    return {
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "candles_streamed": count,
    }


# ------------------------------------------------------------------
# New: Combined market data stream (all symbols, all data types)
# ------------------------------------------------------------------

@shared_task(bind=True, name="data.start_market_data_stream")
def start_market_data_stream(
    self,
    symbols: list[str] | None = None,
    timeframe: str = "1m",
    persist_interval: int = 60,
) -> dict:
    """Stream klines + ticker + bookTicker for all symbols via combined WS.

    Klines are saved on every candle close.
    Ticker and bookTicker are buffered and saved once per persist_interval
    (default 60 seconds = 1 minute).
    """
    from trading_system.data.providers.binance import BinanceProvider

    if symbols is None:
        symbols = _get_symbols()

    provider = BinanceProvider()
    channel_layer = get_channel_layer()
    loop = _get_or_create_event_loop()

    counts = {"klines": 0, "tickers": 0, "book_tickers": 0}
    last_ticker_save: dict[str, float] = {}
    last_book_ticker_save: dict[str, float] = {}

    async def _stream():
        try:
            async for event in provider.stream_market_data(symbols, timeframe):
                evt_type = event["type"]
                data = event["data"]
                now = time.monotonic()

                if evt_type == "kline":
                    _save_candles([data])
                    counts["klines"] += 1

                    sym = data.symbol
                    if channel_layer:
                        await channel_layer.group_send(
                            f"market_{sym}",
                            {"type": "market_update", "data": data.to_dict()},
                        )

                elif evt_type == "ticker":
                    sym = data["symbol"]
                    last_save = last_ticker_save.get(sym, 0)
                    if now - last_save >= persist_interval:
                        _save_ticker(data)
                        last_ticker_save[sym] = now
                        counts["tickers"] += 1

                elif evt_type == "book_ticker":
                    sym = data["symbol"]
                    last_save = last_book_ticker_save.get(sym, 0)
                    if now - last_save >= persist_interval:
                        _save_book_ticker(data)
                        last_book_ticker_save[sym] = now
                        counts["book_tickers"] += 1

        finally:
            await provider.close()

    logger.info(
        "Starting market data stream for %d symbols: %s",
        len(symbols), ", ".join(symbols),
    )
    loop.run_until_complete(_stream())

    return counts


# ------------------------------------------------------------------
# New: Periodic REST tasks (order book, ticker, book ticker)
# ------------------------------------------------------------------

@shared_task(bind=True, name="data.collect_order_books")
def collect_order_books(
    self,
    symbols: list[str] | None = None,
    exchange: str = "binance",
    limit: int | None = None,
) -> dict:
    """Fetch order book depth for all symbols and persist snapshots.

    Designed to run every 1 minute via Celery Beat.
    """
    from trading_system.data.providers.binance import BinanceProvider

    if symbols is None:
        symbols = _get_symbols()
    if limit is None:
        limit = getattr(django_settings, "ORDER_BOOK_DEPTH_LIMIT", 20)

    provider = BinanceProvider()
    loop = _get_or_create_event_loop()

    async def _run():
        try:
            return await provider.fetch_order_books(symbols, limit)
        finally:
            await provider.close()

    snapshots = loop.run_until_complete(_run())

    saved = 0
    for snap in snapshots:
        try:
            _save_order_book(snap)
            saved += 1
        except Exception as exc:
            logger.error("Failed to save order book for %s: %s", snap.get("symbol"), exc)

    logger.info("Order book collection: %d/%d symbols saved", saved, len(symbols))
    return {"symbols": len(symbols), "saved": saved}


@shared_task(bind=True, name="data.collect_tickers")
def collect_tickers(
    self,
    symbols: list[str] | None = None,
    exchange: str = "binance",
) -> dict:
    """Fetch 24h ticker stats for all symbols and persist snapshots.

    Designed to run every 1 minute via Celery Beat.
    """
    from trading_system.data.providers.binance import BinanceProvider

    if symbols is None:
        symbols = _get_symbols()

    provider = BinanceProvider()
    loop = _get_or_create_event_loop()

    async def _run():
        try:
            return await provider.fetch_tickers_24h(symbols)
        finally:
            await provider.close()

    tickers = loop.run_until_complete(_run())

    saved = 0
    for ticker in tickers:
        try:
            _save_ticker(ticker)
            saved += 1
        except Exception as exc:
            logger.error("Failed to save ticker for %s: %s", ticker.get("symbol"), exc)

    logger.info("Ticker collection: %d/%d symbols saved", saved, len(symbols))
    return {"symbols": len(symbols), "saved": saved}


@shared_task(bind=True, name="data.collect_book_tickers")
def collect_book_tickers(
    self,
    symbols: list[str] | None = None,
    exchange: str = "binance",
) -> dict:
    """Fetch best bid/ask for all symbols and persist snapshots.

    Designed to run every 1 minute via Celery Beat.
    """
    from trading_system.data.providers.binance import BinanceProvider

    if symbols is None:
        symbols = _get_symbols()

    provider = BinanceProvider()
    loop = _get_or_create_event_loop()

    async def _run():
        try:
            return await provider.fetch_book_tickers(symbols)
        finally:
            await provider.close()

    book_tickers = loop.run_until_complete(_run())

    saved = 0
    for bt in book_tickers:
        try:
            _save_book_ticker(bt)
            saved += 1
        except Exception as exc:
            logger.error("Failed to save book ticker for %s: %s", bt.get("symbol"), exc)

    logger.info("Book ticker collection: %d/%d symbols saved", saved, len(symbols))
    return {"symbols": len(symbols), "saved": saved}


# ------------------------------------------------------------------
# Existing: CSV import
# ------------------------------------------------------------------

@shared_task(bind=True, name="data.ingest_csv")
def ingest_csv(
    self,
    file_path: str,
    symbol: str,
    exchange: str = "manual",
    timeframe: str = "1d",
    column_map: dict | None = None,
) -> dict:
    """Import candles from a CSV file into the database."""
    from trading_system.data.providers.csv_loader import CSVProvider

    provider = CSVProvider(
        file_path=file_path,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        column_map=column_map,
    )

    loop = _get_or_create_event_loop()

    async def _run():
        start = datetime(2000, 1, 1, tzinfo=timezone.utc)
        end = datetime(2100, 1, 1, tzinfo=timezone.utc)
        return await provider.fetch_historical(symbol, timeframe, start, end)

    candles = loop.run_until_complete(_run())
    saved = _save_candles(candles)

    logger.info("CSV import complete: %s — %d candles saved", file_path, saved)
    return {
        "file": file_path,
        "symbol": symbol,
        "candles_loaded": len(candles),
        "candles_saved": saved,
    }


# ------------------------------------------------------------------
# Forex collection (Twelve Data)
# ------------------------------------------------------------------

@shared_task(bind=True, name="data.collect_forex")
def collect_forex(
    self,
    symbols: list[str] | None = None,
    timeframe: str = "5m",
    count: int = 1,
) -> dict:
    """Fetch latest forex candles for all configured pairs.

    Designed to run periodically via Celery Beat (every 5 min).
    Each symbol costs 1 API credit; 10 symbols = 10 credits per call.
    At every 5 min: 10 × 288 polls/day = 2,880 — needs paid tier.
    At every 15 min: 10 × 96 = 960 — needs paid tier.
    For free tier (800/day), poll every 30 min or reduce symbol count.
    """
    if symbols is None:
        symbols = _get_forex_symbols()

    provider = _get_provider("twelvedata")
    loop = _get_or_create_event_loop()

    async def _run():
        results = []
        for sym in symbols:
            try:
                candles = await provider.fetch_latest(sym, timeframe, count)
                if candles:
                    _save_candles(candles)
                    results.append({"symbol": sym, "candles": len(candles)})
            except Exception as exc:
                logger.error("Forex fetch failed for %s: %s", sym, exc)
                results.append({"symbol": sym, "error": str(exc)})
            await asyncio.sleep(0.2)
        await provider.close()
        return results

    results = loop.run_until_complete(_run())
    saved = sum(r.get("candles", 0) for r in results)

    logger.info("Forex collection: %d candles saved for %d symbols", saved, len(symbols))
    return {"symbols": len(symbols), "saved": saved, "details": results}


@shared_task(bind=True, name="data.backfill_forex")
def backfill_forex(
    self,
    symbols: list[str] | None = None,
    timeframe: str = "5m",
    start_iso: str = "",
    end_iso: str = "",
) -> dict:
    """Backfill historical forex data for all configured pairs."""
    if symbols is None:
        symbols = _get_forex_symbols()

    if not start_iso:
        start_iso = (datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )).isoformat()
    if not end_iso:
        end_iso = datetime.now(tz=timezone.utc).isoformat()

    start = datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc)

    provider = _get_provider("twelvedata")
    loop = _get_or_create_event_loop()

    async def _run():
        results = {}
        for sym in symbols:
            try:
                candles = await provider.fetch_historical(sym, timeframe, start, end)
                saved = _save_candles(candles)
                results[sym] = {"fetched": len(candles), "saved": saved}
                logger.info("Forex backfill %s: %d candles saved", sym, saved)
            except Exception as exc:
                logger.error("Forex backfill failed for %s: %s", sym, exc)
                results[sym] = {"error": str(exc)}
            await asyncio.sleep(0.5)
        await provider.close()
        return results

    results = loop.run_until_complete(_run())
    return results


# ------------------------------------------------------------------
# Stock collection (Polygon.io — OHLCV + VWAP + trade count)
# ------------------------------------------------------------------

@shared_task(bind=True, name="data.collect_stocks")
def collect_stocks(
    self,
    symbols: list[str] | None = None,
    timeframe: str = "1m",
    count: int = 1,
) -> dict:
    """Fetch latest stock candles from Polygon.io.

    Each bar includes VWAP and number-of-trades.
    Free tier: 5 calls/min — rate limited internally.
    """
    if symbols is None:
        symbols = _get_stock_symbols()

    provider = _get_provider("polygon")
    loop = _get_or_create_event_loop()

    async def _run():
        results = []
        for sym in symbols:
            try:
                candles = await provider.fetch_latest(sym, timeframe, count)
                if candles:
                    _save_candles(candles)
                    results.append({"symbol": sym, "candles": len(candles)})
            except Exception as exc:
                logger.error("Stock fetch failed for %s: %s", sym, exc)
                results.append({"symbol": sym, "error": str(exc)})
        await provider.close()
        return results

    results = loop.run_until_complete(_run())
    saved = sum(r.get("candles", 0) for r in results)

    logger.info("Stock collection: %d candles saved for %d symbols", saved, len(symbols))
    return {"symbols": len(symbols), "saved": saved, "details": results}


@shared_task(bind=True, name="data.backfill_stocks")
def backfill_stocks(
    self,
    symbols: list[str] | None = None,
    timeframe: str = "1m",
    start_iso: str = "",
    end_iso: str = "",
) -> dict:
    """Backfill historical stock data from Polygon.io."""
    if symbols is None:
        symbols = _get_stock_symbols()

    if not start_iso:
        start_iso = (datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )).isoformat()
    if not end_iso:
        end_iso = datetime.now(tz=timezone.utc).isoformat()

    start = datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc)

    provider = _get_provider("polygon")
    loop = _get_or_create_event_loop()

    async def _run():
        results = {}
        for sym in symbols:
            try:
                candles = await provider.fetch_historical(sym, timeframe, start, end)
                saved = _save_candles(candles)
                results[sym] = {"fetched": len(candles), "saved": saved}
                logger.info("Stock backfill %s: %d candles saved", sym, saved)
            except Exception as exc:
                logger.error("Stock backfill failed for %s: %s", sym, exc)
                results[sym] = {"error": str(exc)}
        await provider.close()
        return results

    results = loop.run_until_complete(_run())
    return results


@shared_task(bind=True, name="data.collect_stock_quotes")
def collect_stock_quotes(
    self,
    symbols: list[str] | None = None,
) -> dict:
    """Fetch NBBO bid/ask quotes for stocks from Polygon.io.

    Stores in BookTickerSnapshot for parity with crypto bid/ask data.
    """
    if symbols is None:
        symbols = _get_stock_symbols()

    provider = _get_provider("polygon")
    loop = _get_or_create_event_loop()

    async def _run():
        quotes = await provider.fetch_nbbo_batch(symbols)
        for q in quotes:
            _save_book_ticker(q)
        await provider.close()
        return len(quotes)

    saved = loop.run_until_complete(_run())
    logger.info("Stock NBBO quotes: %d saved", saved)
    return {"quotes_saved": saved}


@shared_task(bind=True, name="data.collect_forex_quotes")
def collect_forex_quotes(
    self,
    symbols: list[str] | None = None,
) -> dict:
    """Fetch price quotes for forex pairs from Twelve Data.

    Stores price snapshot data in TickerSnapshot.
    """
    if symbols is None:
        symbols = _get_forex_symbols()

    provider = _get_provider("twelvedata")
    loop = _get_or_create_event_loop()

    async def _run():
        results = []
        for sym in symbols:
            try:
                quote = await provider.fetch_quote(sym)
                if quote:
                    _save_ticker(quote)
                    results.append(sym)
            except Exception as exc:
                logger.error("Forex quote failed for %s: %s", sym, exc)
            await asyncio.sleep(0.3)
        await provider.close()
        return results

    saved_syms = loop.run_until_complete(_run())
    logger.info("Forex quotes: %d saved", len(saved_syms))
    return {"quotes_saved": len(saved_syms)}
