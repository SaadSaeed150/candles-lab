"""
Management command to collect market data directly (without Celery).

Usage:
    python manage.py collect_data                    # backfill last 4h, 1m candles (Binance crypto)
    python manage.py collect_data --hours 24         # backfill last 24h
    python manage.py collect_data --timeframe 5m     # 5-minute candles
    python manage.py collect_data --symbols BTCUSDT ETHUSDT  # specific symbols
    python manage.py collect_data --order-books      # also fetch order book snapshots
    python manage.py collect_data --all              # fetch everything (candles + order book + ticker + book ticker)
    python manage.py collect_data --forex            # fetch top 10 forex pairs via Twelve Data
    python manage.py collect_data --forex --symbols EUR/USD GBP/USD
    python manage.py collect_data --stocks           # fetch top 10 US stocks via Finnhub
    python manage.py collect_data --stocks --symbols AAPL MSFT NVDA
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

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

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch market data from Binance and store it in the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbols", nargs="+", default=None,
            help="Symbols to fetch (default: all configured)",
        )
        parser.add_argument(
            "--timeframe", default="1m",
            help="Candle timeframe (default: 1m)",
        )
        parser.add_argument(
            "--hours", type=int, default=4,
            help="Hours of history to backfill (default: 4)",
        )
        parser.add_argument(
            "--order-books", action="store_true",
            help="Also fetch order book snapshots",
        )
        parser.add_argument(
            "--tickers", action="store_true",
            help="Also fetch 24h ticker stats",
        )
        parser.add_argument(
            "--book-tickers", action="store_true",
            help="Also fetch best bid/ask",
        )
        parser.add_argument(
            "--all", action="store_true", dest="fetch_all",
            help="Fetch everything (candles + order book + ticker + book ticker)",
        )
        parser.add_argument(
            "--depth", type=int, default=20,
            help="Order book depth limit (default: 20)",
        )
        parser.add_argument(
            "--forex", action="store_true",
            help="Fetch forex data from Twelve Data instead of crypto from Binance",
        )
        parser.add_argument(
            "--stocks", action="store_true",
            help="Fetch US stock data from Finnhub instead of crypto from Binance",
        )

    def handle(self, *args, **options):
        if options["stocks"]:
            self._handle_stocks(options)
        elif options["forex"]:
            self._handle_forex(options)
        else:
            self._handle_crypto(options)

        self.stdout.write(self.style.SUCCESS("\n--- Collection Complete ---"))
        self.stdout.write(f"  MarketData rows:        {MarketData.objects.count()}")
        self.stdout.write(f"  OrderBookSnapshot rows:  {OrderBookSnapshot.objects.count()}")
        self.stdout.write(f"  TickerSnapshot rows:     {TickerSnapshot.objects.count()}")
        self.stdout.write(f"  BookTickerSnapshot rows: {BookTickerSnapshot.objects.count()}")

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
        hours = options["hours"]

        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(hours=hours)

        self.stdout.write(
            f"\n[FOREX] Collecting data for {len(symbols)} pairs: {', '.join(symbols)}"
        )
        self.stdout.write(f"Timeframe: {timeframe} | History: {hours}h | [{start} → {end}]")
        self.stdout.write(f"Provider: Twelve Data")
        self.stdout.write("")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        provider = TwelveDataProvider(api_key=api_key)

        try:
            total_candles = 0
            for i, symbol in enumerate(symbols, 1):
                self.stdout.write(
                    f"  [{i}/{len(symbols)}] Fetching {symbol}...", ending=""
                )
                try:
                    candles = loop.run_until_complete(
                        provider.fetch_historical(symbol, timeframe, start, end)
                    )
                    saved = _save_candles(candles)
                    total_candles += saved
                    self.stdout.write(self.style.SUCCESS(f" {saved} candles saved"))
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f" FAILED: {exc}"))
                loop.run_until_complete(asyncio.sleep(0.5))

            self.stdout.write(self.style.SUCCESS(
                f"\n  Total forex candles saved: {total_candles}"
            ))
        finally:
            loop.run_until_complete(provider.close())
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
        hours = options["hours"]

        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(hours=hours)

        self.stdout.write(
            f"\n[STOCKS] Collecting data for {len(symbols)} symbols: {', '.join(symbols)}"
        )
        self.stdout.write(f"Timeframe: {timeframe} | History: {hours}h | [{start} → {end}]")
        self.stdout.write(f"Provider: Polygon.io (OHLCV + VWAP + trades)")
        self.stdout.write("")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        provider = PolygonProvider(api_key=api_key)

        try:
            total_candles = 0
            for i, symbol in enumerate(symbols, 1):
                self.stdout.write(
                    f"  [{i}/{len(symbols)}] Fetching {symbol}...", ending=""
                )
                try:
                    candles = loop.run_until_complete(
                        provider.fetch_historical(symbol, timeframe, start, end)
                    )
                    saved = _save_candles(candles)
                    total_candles += saved
                    self.stdout.write(self.style.SUCCESS(f" {saved} candles saved"))
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f" FAILED: {exc}"))

            self.stdout.write(self.style.SUCCESS(
                f"\n  Total stock candles saved: {total_candles}"
            ))
        finally:
            loop.run_until_complete(provider.close())
            loop.close()

    def _handle_crypto(self, options):
        from trading_system.data.providers.binance import BinanceProvider

        symbols = options["symbols"] or getattr(
            settings, "TRADING_SYMBOLS",
            ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
             "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT"],
        )
        timeframe = options["timeframe"]
        hours = options["hours"]
        fetch_all = options["fetch_all"]
        fetch_order_books = options["order_books"] or fetch_all
        fetch_tickers = options["tickers"] or fetch_all
        fetch_book_tickers = options["book_tickers"] or fetch_all
        depth = options["depth"]

        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(hours=hours)

        self.stdout.write(
            f"\n[CRYPTO] Collecting data for {len(symbols)} symbols: {', '.join(symbols)}"
        )
        self.stdout.write(f"Timeframe: {timeframe} | History: {hours}h | [{start} → {end}]")
        self.stdout.write("")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        provider = BinanceProvider()

        try:
            total_candles = 0
            for i, symbol in enumerate(symbols, 1):
                self.stdout.write(f"  [{i}/{len(symbols)}] Fetching {symbol} klines...", ending="")
                try:
                    candles = loop.run_until_complete(
                        provider.fetch_historical(symbol, timeframe, start, end)
                    )
                    saved = _save_candles(candles)
                    total_candles += saved
                    self.stdout.write(self.style.SUCCESS(f" {saved} candles saved"))
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f" FAILED: {exc}"))

            self.stdout.write(self.style.SUCCESS(
                f"\n  Total candles saved: {total_candles}"
            ))

            if fetch_order_books:
                self.stdout.write(f"\n  Fetching order books (depth={depth})...")
                try:
                    snapshots = loop.run_until_complete(
                        provider.fetch_order_books(symbols, depth)
                    )
                    for snap in snapshots:
                        _save_order_book(snap)
                    self.stdout.write(self.style.SUCCESS(
                        f"  {len(snapshots)} order book snapshots saved"
                    ))
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f"  Order books FAILED: {exc}"))

            if fetch_tickers:
                self.stdout.write("\n  Fetching 24h tickers...")
                try:
                    tickers = loop.run_until_complete(
                        provider.fetch_tickers_24h(symbols)
                    )
                    for ticker in tickers:
                        _save_ticker(ticker)
                    self.stdout.write(self.style.SUCCESS(
                        f"  {len(tickers)} ticker snapshots saved"
                    ))
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f"  Tickers FAILED: {exc}"))

            if fetch_book_tickers:
                self.stdout.write("\n  Fetching book tickers...")
                try:
                    book_tickers = loop.run_until_complete(
                        provider.fetch_book_tickers(symbols)
                    )
                    for bt in book_tickers:
                        _save_book_ticker(bt)
                    self.stdout.write(self.style.SUCCESS(
                        f"  {len(book_tickers)} book ticker snapshots saved"
                    ))
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f"  Book tickers FAILED: {exc}"))

        finally:
            loop.run_until_complete(provider.close())
            loop.close()
