"""
Management command to run live market data collection.

Crypto (default): WebSocket stream for klines + ticker + bookTicker.
Forex (--forex): Periodic REST polling via Twelve Data API.
Stocks (--stocks): Periodic REST polling via Finnhub API.

Usage:
    python manage.py live_collect                              # crypto via Binance WS
    python manage.py live_collect --symbols BTCUSDT ETHUSDT
    python manage.py live_collect --forex                      # forex via Twelve Data polling
    python manage.py live_collect --forex --symbols EUR/USD GBP/USD
    python manage.py live_collect --stocks                     # US stocks via Finnhub polling
    python manage.py live_collect --stocks --symbols AAPL MSFT NVDA
    python manage.py live_collect --stocks --poll-interval 60  # poll every 1 min
"""

import asyncio
import logging
import signal
import time
from datetime import datetime, timezone

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand

from trading_system.data.models import (
    BookTickerSnapshot,
    MarketData,
    OrderBookSnapshot,
    TickerSnapshot,
)
from trading_system.data.tasks import (
    _save_book_ticker,
    _save_candles,
    _save_order_book,
    _save_ticker,
)

_async_save_candles = sync_to_async(_save_candles, thread_sensitive=True)
_async_save_order_book = sync_to_async(_save_order_book, thread_sensitive=True)
_async_save_ticker = sync_to_async(_save_ticker, thread_sensitive=True)
_async_save_book_ticker = sync_to_async(_save_book_ticker, thread_sensitive=True)
_async_candle_count = sync_to_async(lambda: MarketData.objects.count(), thread_sensitive=True)
_async_ticker_count = sync_to_async(lambda: TickerSnapshot.objects.count(), thread_sensitive=True)
_async_ob_count = sync_to_async(lambda: OrderBookSnapshot.objects.count(), thread_sensitive=True)
_async_bt_count = sync_to_async(lambda: BookTickerSnapshot.objects.count(), thread_sensitive=True)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run live market data collection (crypto, forex, or stocks)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbols", nargs="+", default=None,
            help="Symbols to track (default: all configured)",
        )
        parser.add_argument(
            "--timeframe", default="1m",
            help="Candle timeframe (default: 1m)",
        )
        parser.add_argument(
            "--order-book-interval", type=int, default=60,
            help="Order book fetch interval in seconds (default: 60)",
        )
        parser.add_argument(
            "--forex", action="store_true",
            help="Collect forex data via Twelve Data polling instead of crypto",
        )
        parser.add_argument(
            "--stocks", action="store_true",
            help="Collect US stock data via Finnhub polling instead of crypto",
        )
        parser.add_argument(
            "--poll-interval", type=int, default=None,
            help="Poll interval in seconds (default: from settings)",
        )

    def handle(self, *args, **options):
        if options["stocks"]:
            self._handle_stocks(options)
        elif options["forex"]:
            self._handle_forex(options)
        else:
            self._handle_crypto(options)

    def _handle_forex(self, options):
        from trading_system.data.providers.twelvedata import TwelveDataProvider

        api_key = getattr(settings, "TWELVEDATA_API_KEY", "")
        if not api_key:
            self.stdout.write(self.style.ERROR(
                "TWELVEDATA_API_KEY not set. Add it to your .env file."
            ))
            return

        symbols = options["symbols"] or getattr(
            settings, "FOREX_SYMBOLS",
            ["EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD",
             "USD/CHF", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY"],
        )
        timeframe = options["timeframe"]
        poll_interval = options["poll_interval"] or getattr(
            settings, "FOREX_POLL_INTERVAL_SECONDS", 300
        )

        self.stdout.write(self.style.SUCCESS(
            f"\n  [FOREX] Starting live collection for {len(symbols)} pairs"
        ))
        self.stdout.write(f"  Pairs: {', '.join(symbols)}")
        self.stdout.write(f"  Timeframe: {timeframe}")
        self.stdout.write(f"  Poll interval: {poll_interval}s")
        self.stdout.write(self.style.WARNING("  Press Ctrl+C to stop\n"))

        provider = TwelveDataProvider(api_key=api_key)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        shutdown = asyncio.Event()

        def _signal_handler():
            self.stdout.write(self.style.WARNING("\n  Shutting down..."))
            shutdown.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        async def forex_poller():
            """Poll Twelve Data for latest candles at regular intervals."""
            poll_count = 0
            total_saved = 0

            while not shutdown.is_set():
                poll_count += 1
                batch_saved = 0

                for sym in symbols:
                    if shutdown.is_set():
                        break
                    try:
                        candles = await provider.fetch_latest(sym, timeframe, count=2)
                        if candles:
                            saved = await _async_save_candles(candles)
                            batch_saved += saved
                            total_saved += saved
                            latest = candles[-1]
                            self.stdout.write(self.style.SUCCESS(
                                f"  [FX] {sym} close={latest.close:.5f} "
                                f"vol={latest.volume:.0f}"
                            ))
                    except Exception as exc:
                        logger.error("Forex poll failed for %s: %s", sym, exc)
                    await asyncio.sleep(0.3)

                cc = await _async_candle_count()
                self.stdout.write(
                    f"  [POLL #{poll_count}] {batch_saved} candles saved | "
                    f"Total DB candles: {cc}"
                )

                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)
                    break
                except asyncio.TimeoutError:
                    pass

        async def main():
            task = asyncio.create_task(forex_poller())
            await shutdown.wait()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await provider.close()
            cc = await _async_candle_count()
            self.stdout.write(self.style.SUCCESS("\n  Forex live collection stopped."))
            self.stdout.write(f"  Total MarketData rows: {cc}")

        loop.run_until_complete(main())
        loop.close()

    def _handle_stocks(self, options):
        from trading_system.data.providers.polygon import PolygonProvider

        api_key = getattr(settings, "POLYGON_API_KEY", "")
        if not api_key:
            self.stdout.write(self.style.ERROR(
                "POLYGON_API_KEY not set. Add it to your .env file.\n"
                "Get a free key at https://polygon.io"
            ))
            return

        symbols = options["symbols"] or getattr(
            settings, "STOCK_SYMBOLS",
            ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
             "META", "TSLA", "JPM", "V", "AVGO"],
        )
        timeframe = options["timeframe"]
        poll_interval = options["poll_interval"] or getattr(
            settings, "STOCK_POLL_INTERVAL_SECONDS", 60
        )

        self.stdout.write(self.style.SUCCESS(
            f"\n  [STOCKS] Starting live collection for {len(symbols)} symbols"
        ))
        self.stdout.write(f"  Symbols: {', '.join(symbols)}")
        self.stdout.write(f"  Timeframe: {timeframe}")
        self.stdout.write(f"  Poll interval: {poll_interval}s")
        self.stdout.write(f"  Provider: Polygon.io (OHLCV + VWAP + trades + NBBO)")
        self.stdout.write(self.style.WARNING("  Press Ctrl+C to stop\n"))

        provider = PolygonProvider(api_key=api_key)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        shutdown = asyncio.Event()

        def _signal_handler():
            self.stdout.write(self.style.WARNING("\n  Shutting down..."))
            shutdown.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        async def stock_poller():
            poll_count = 0

            while not shutdown.is_set():
                poll_count += 1
                batch_saved = 0

                for sym in symbols:
                    if shutdown.is_set():
                        break
                    try:
                        candles = await provider.fetch_latest(sym, timeframe, count=2)
                        if candles:
                            saved = await _async_save_candles(candles)
                            batch_saved += saved
                            latest = candles[-1]
                            vwap = latest.extra.get("vwap", 0)
                            trades = latest.extra.get("num_trades", 0)
                            self.stdout.write(self.style.SUCCESS(
                                f"  [STK] {sym} close=${latest.close:.2f} "
                                f"vwap=${vwap:.2f} trades={trades} "
                                f"vol={latest.volume:.0f}"
                            ))
                    except Exception as exc:
                        logger.error("Stock poll failed for %s: %s", sym, exc)

                # Also fetch NBBO quotes every cycle
                try:
                    for sym in symbols:
                        if shutdown.is_set():
                            break
                        nbbo = await provider.fetch_nbbo(sym)
                        if nbbo:
                            await _async_save_book_ticker(nbbo)
                except Exception as exc:
                    logger.error("NBBO fetch failed: %s", exc)

                cc = await _async_candle_count()
                bc = await _async_bt_count()
                self.stdout.write(
                    f"  [POLL #{poll_count}] {batch_saved} candles | "
                    f"DB: {cc} candles, {bc} bid/ask quotes"
                )

                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)
                    break
                except asyncio.TimeoutError:
                    pass

        async def main():
            task = asyncio.create_task(stock_poller())
            await shutdown.wait()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await provider.close()
            cc = await _async_candle_count()
            bc = await _async_bt_count()
            self.stdout.write(self.style.SUCCESS("\n  Stock live collection stopped."))
            self.stdout.write(f"  Total MarketData rows: {cc}")
            self.stdout.write(f"  Total BookTicker rows: {bc}")

        loop.run_until_complete(main())
        loop.close()

    def _handle_crypto(self, options):
        from trading_system.data.providers.binance import BinanceProvider

        symbols = options["symbols"] or getattr(
            settings, "TRADING_SYMBOLS",
            ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
             "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"],
        )
        timeframe = options["timeframe"]
        ob_interval = options["order_book_interval"]

        self.stdout.write(self.style.SUCCESS(
            f"\n  Starting live collection for {len(symbols)} symbols"
        ))
        self.stdout.write(f"  Symbols: {', '.join(symbols)}")
        self.stdout.write(f"  Timeframe: {timeframe}")
        self.stdout.write(f"  Order book interval: {ob_interval}s")
        self.stdout.write(self.style.WARNING("  Press Ctrl+C to stop\n"))

        provider = BinanceProvider()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        shutdown = asyncio.Event()

        def _signal_handler():
            self.stdout.write(self.style.WARNING("\n  Shutting down..."))
            shutdown.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        async def order_book_collector():
            while not shutdown.is_set():
                try:
                    snapshots = await provider.fetch_order_books(symbols, 20)
                    for snap in snapshots:
                        await _async_save_order_book(snap)
                    self.stdout.write(
                        f"  [OB] {len(snapshots)} order book snapshots saved"
                    )
                except Exception as exc:
                    logger.error("Order book collection failed: %s", exc)

                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=ob_interval)
                    break
                except asyncio.TimeoutError:
                    pass

        async def stream_collector():
            persist_interval = 60
            last_ticker_save = {}
            last_book_ticker_save = {}

            counts = {"klines": 0, "tickers": 0, "book_tickers": 0}
            last_report = time.monotonic()

            try:
                async for event in provider.stream_market_data(symbols, timeframe):
                    if shutdown.is_set():
                        break

                    evt_type = event["type"]
                    data = event["data"]
                    now = time.monotonic()

                    if evt_type == "kline":
                        await _async_save_candles([data])
                        counts["klines"] += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"  [KLINE] {data.symbol} close={data.close:.2f} "
                            f"vol={data.volume:.4f} "
                            f"bp={data.extra.get('buy_pressure', 0):.1%}"
                        ))

                    elif evt_type == "ticker":
                        sym = data["symbol"]
                        last_save = last_ticker_save.get(sym, 0)
                        if now - last_save >= persist_interval:
                            await _async_save_ticker(data)
                            last_ticker_save[sym] = now
                            counts["tickers"] += 1

                    elif evt_type == "book_ticker":
                        sym = data["symbol"]
                        last_save = last_book_ticker_save.get(sym, 0)
                        if now - last_save >= persist_interval:
                            await _async_save_book_ticker(data)
                            last_book_ticker_save[sym] = now
                            counts["book_tickers"] += 1

                    if now - last_report >= 60:
                        cc = await _async_candle_count()
                        tc = await _async_ticker_count()
                        oc = await _async_ob_count()
                        self.stdout.write(
                            f"  [STATS] klines={counts['klines']} "
                            f"tickers={counts['tickers']} "
                            f"book_tickers={counts['book_tickers']} | "
                            f"DB: {cc} candles, {tc} tickers, {oc} order books"
                        )
                        last_report = now

            except asyncio.CancelledError:
                pass

        async def main():
            tasks = [
                asyncio.create_task(stream_collector()),
                asyncio.create_task(order_book_collector()),
            ]

            await shutdown.wait()

            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await provider.close()

            cc = await _async_candle_count()
            tc = await _async_ticker_count()
            oc = await _async_ob_count()
            bc = await _async_bt_count()
            self.stdout.write(self.style.SUCCESS("\n  Live collection stopped."))
            self.stdout.write(f"  MarketData rows:        {cc}")
            self.stdout.write(f"  OrderBookSnapshot rows:  {oc}")
            self.stdout.write(f"  TickerSnapshot rows:     {tc}")
            self.stdout.write(f"  BookTickerSnapshot rows: {bc}")

        loop.run_until_complete(main())
        loop.close()
