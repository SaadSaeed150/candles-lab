"""
Backfill years of historical data for backtesting.

Crypto:  Downloads bulk CSV from Binance Data Vision (NO API key needed).
Forex:   Uses Twelve Data API (needs TWELVEDATA_API_KEY).
Stocks:  Uses Polygon.io API (needs POLYGON_API_KEY).

Usage:
    python manage.py backfill_history --crypto                          # 5 yrs crypto
    python manage.py backfill_history --crypto --years 2                # 2 yrs crypto
    python manage.py backfill_history --crypto --symbols BTCUSDT ETHUSDT
    python manage.py backfill_history --forex                           # 5 yrs forex
    python manage.py backfill_history --stocks                          # 5 yrs stocks
    python manage.py backfill_history --all                             # everything
    python manage.py backfill_history --crypto --timeframe 5m           # 5-min candles
"""

import asyncio
import csv
import io
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import aiohttp
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand

from trading_system.data.models import MarketData

logger = logging.getLogger(__name__)

BINANCE_DATA_URL = "https://data.binance.vision/data/spot/monthly/klines"


class Command(BaseCommand):
    help = "Backfill years of historical data for backtesting"

    def add_arguments(self, parser):
        parser.add_argument(
            "--crypto", action="store_true",
            help="Backfill crypto from Binance Data Vision (no API key needed)",
        )
        parser.add_argument(
            "--forex", action="store_true",
            help="Backfill forex from Twelve Data API",
        )
        parser.add_argument(
            "--stocks", action="store_true",
            help="Backfill US stocks from Polygon.io API",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="Backfill all markets",
        )
        parser.add_argument(
            "--years", type=int, default=5,
            help="Years of history to fetch (default: 5)",
        )
        parser.add_argument(
            "--symbols", nargs="+", default=None,
            help="Specific symbols to backfill",
        )
        parser.add_argument(
            "--timeframe", default="1m",
            help="Candle timeframe (default: 1m, use 5m for forex)",
        )

    def handle(self, *args, **options):
        do_crypto = options["crypto"] or options["all"]
        do_forex = options["forex"] or options["all"]
        do_stocks = options["stocks"] or options["all"]

        if not (do_crypto or do_forex or do_stocks):
            self.stdout.write(self.style.ERROR(
                "Specify --crypto, --forex, --stocks, or --all"
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n  HISTORICAL DATA BACKFILL — {options['years']} YEARS\n{'='*60}"
        ))

        if do_crypto:
            self._backfill_crypto(options)
        if do_forex:
            self._backfill_forex(options)
        if do_stocks:
            self._backfill_stocks(options)

        total = MarketData.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n  DONE — Total MarketData rows: {total:,}\n{'='*60}"
        ))

    # ------------------------------------------------------------------
    # CRYPTO — Binance Data Vision (free, no API key)
    # ------------------------------------------------------------------

    def _backfill_crypto(self, options):
        symbols = options["symbols"] or getattr(
            settings, "TRADING_SYMBOLS",
            ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
             "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"],
        )
        tf = options["timeframe"]
        years = options["years"]

        months = self._generate_months(years)

        self.stdout.write(self.style.SUCCESS(
            f"\n  [CRYPTO] Binance Data Vision"
        ))
        self.stdout.write(f"  Symbols: {len(symbols)} | Timeframe: {tf}")
        self.stdout.write(f"  Range: {months[0][0]}-{months[0][1]:02d} → "
                          f"{months[-1][0]}-{months[-1][1]:02d} "
                          f"({len(months)} months × {len(symbols)} symbols "
                          f"= {len(months) * len(symbols)} files)")
        self.stdout.write("")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        total_saved = 0
        for si, symbol in enumerate(symbols, 1):
            sym_saved = loop.run_until_complete(
                self._download_crypto_symbol(symbol, tf, months, si, len(symbols))
            )
            total_saved += sym_saved

        loop.close()

        self.stdout.write(self.style.SUCCESS(
            f"\n  [CRYPTO] Total: {total_saved:,} candles saved"
        ))

    async def _download_crypto_symbol(
        self, symbol: str, tf: str, months: list, idx: int, total: int,
    ) -> int:
        """Download all monthly ZIPs for one symbol and import."""
        saved = 0

        _async_count = sync_to_async(
            lambda s, e, t, y, m: MarketData.objects.filter(
                symbol=s, exchange=e, timeframe=t,
                time__year=y, time__month=m,
            ).count(),
            thread_sensitive=True,
        )
        _async_bulk_save = sync_to_async(self._bulk_save, thread_sensitive=True)

        async with aiohttp.ClientSession() as session:
            for mi, (year, month) in enumerate(months):
                tag = f"[{idx}/{total}] {symbol} {year}-{month:02d}"

                existing = await _async_count(symbol, "binance", tf, year, month)
                if existing > 1000:
                    self.stdout.write(f"  {tag} — skipped ({existing:,} rows exist)")
                    continue

                url = (
                    f"{BINANCE_DATA_URL}/{symbol}/{tf}/"
                    f"{symbol}-{tf}-{year}-{month:02d}.zip"
                )

                try:
                    async with session.get(url) as resp:
                        if resp.status == 404:
                            self.stdout.write(
                                f"  {tag} — not available (pre-listing)"
                            )
                            continue
                        if resp.status != 200:
                            self.stdout.write(self.style.ERROR(
                                f"  {tag} — HTTP {resp.status}"
                            ))
                            continue
                        data = await resp.read()

                    candles = self._parse_binance_zip(data, symbol, tf)
                    if candles:
                        batch_saved = await _async_bulk_save(candles)
                        saved += batch_saved
                        self.stdout.write(self.style.SUCCESS(
                            f"  {tag} — {batch_saved:,} candles"
                        ))
                    else:
                        self.stdout.write(f"  {tag} — empty")

                except Exception as exc:
                    self.stdout.write(self.style.ERROR(
                        f"  {tag} — FAILED: {exc}"
                    ))

                await asyncio.sleep(0.1)

        return saved

    def _parse_binance_zip(
        self, zip_data: bytes, symbol: str, tf: str,
    ) -> list:
        """Parse a Binance Data Vision ZIP file into MarketData objects.

        CSV columns (no header):
        0: open_time (ms), 1: open, 2: high, 3: low, 4: close,
        5: volume, 6: close_time (ms), 7: quote_volume,
        8: num_trades, 9: taker_buy_base_vol, 10: taker_buy_quote_vol,
        11: ignore
        """
        objects = []

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for name in zf.namelist():
                if not name.endswith(".csv"):
                    continue
                with zf.open(name) as f:
                    reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                    for row in reader:
                        if len(row) < 11:
                            continue
                        try:
                            o = float(row[1])
                            h = float(row[2])
                            l = float(row[3])
                            c = float(row[4])
                            v = float(row[5])
                            quote_vol = float(row[7])
                            num_trades = int(row[8])
                            taker_buy_base = float(row[9])
                            taker_buy_quote = float(row[10])

                            hl_range = h - l if h != l else 1e-10

                            extra = {
                                "close_time": int(row[6]),
                                "quote_volume": quote_vol,
                                "num_trades": num_trades,
                                "taker_buy_base_volume": taker_buy_base,
                                "taker_buy_quote_volume": taker_buy_quote,
                                "open": o, "high": h, "low": l,
                                "close": c, "volume": v,
                                "buy_pressure": (
                                    round(taker_buy_base / v, 6) if v else 0
                                ),
                                "vwap": (
                                    round(quote_vol / v, 8) if v else 0
                                ),
                                "volume_per_trade": (
                                    round(v / num_trades, 8) if num_trades else 0
                                ),
                                "body_ratio": round(abs(c - o) / hl_range, 6),
                                "upper_wick_ratio": round(
                                    (h - max(o, c)) / hl_range, 6
                                ),
                                "lower_wick_ratio": round(
                                    (min(o, c) - l) / hl_range, 6
                                ),
                            }

                            objects.append(MarketData(
                                symbol=symbol,
                                exchange="binance",
                                timeframe=tf,
                                time=datetime.fromtimestamp(
                                    int(row[0]) / 1000, tz=timezone.utc
                                ),
                                open=Decimal(row[1]),
                                high=Decimal(row[2]),
                                low=Decimal(row[3]),
                                close=Decimal(row[4]),
                                volume=Decimal(row[5]),
                                extra=extra,
                            ))
                        except (ValueError, IndexError, ArithmeticError):
                            continue

        return objects

    # ------------------------------------------------------------------
    # FOREX — Twelve Data API
    # ------------------------------------------------------------------

    def _backfill_forex(self, options):
        from trading_system.data.providers.twelvedata import TwelveDataProvider

        api_key = getattr(settings, "TWELVEDATA_API_KEY", "")
        if not api_key:
            self.stdout.write(self.style.ERROR(
                "  [FOREX] TWELVEDATA_API_KEY not set — skipping.\n"
                "  Get a free key at https://twelvedata.com and add to .env"
            ))
            return

        symbols = options["symbols"] or getattr(
            settings, "FOREX_SYMBOLS",
            ["EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD",
             "USD/CHF", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY"],
        )
        tf = options["timeframe"] if options["timeframe"] != "1m" else "5m"
        years = options["years"]

        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=years * 365)

        self.stdout.write(self.style.SUCCESS(f"\n  [FOREX] Twelve Data API"))
        self.stdout.write(f"  Symbols: {len(symbols)} | Timeframe: {tf}")
        self.stdout.write(f"  Range: {start.date()} → {end.date()}")
        self.stdout.write(f"  Rate limit: 8 req/min, 800 req/day (free tier)")
        self.stdout.write("")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        provider = TwelveDataProvider(api_key=api_key)
        total_saved = 0

        for si, symbol in enumerate(symbols, 1):
            self.stdout.write(f"  [{si}/{len(symbols)}] {symbol}...", ending="")
            try:
                candles = loop.run_until_complete(
                    self._fetch_forex_chunked(provider, symbol, tf, start, end)
                )
                if candles:
                    saved = self._bulk_save_candles(candles)
                    total_saved += saved
                    self.stdout.write(self.style.SUCCESS(f" {saved:,} candles"))
                else:
                    self.stdout.write(" no data")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f" FAILED: {exc}"))

        loop.run_until_complete(provider.close())
        loop.close()

        self.stdout.write(self.style.SUCCESS(
            f"\n  [FOREX] Total: {total_saved:,} candles saved"
        ))

    async def _fetch_forex_chunked(
        self, provider, symbol: str, tf: str,
        start: datetime, end: datetime,
    ) -> list:
        """Fetch forex data in chunks to respect rate limits.

        Twelve Data returns max 5000 candles per request.
        Free tier: 8 requests/minute.
        """
        all_candles = []
        chunk_end = end
        tf_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
        interval = tf_seconds.get(tf, 300)
        chunk_delta = timedelta(seconds=interval * 4999)

        while chunk_end > start:
            chunk_start = max(start, chunk_end - chunk_delta)

            try:
                candles = await provider.fetch_historical(
                    symbol, tf, chunk_start, chunk_end
                )
                if candles:
                    all_candles.extend(candles)
                if not candles or len(candles) < 100:
                    break
            except Exception as exc:
                logger.error("Forex chunk fetch error: %s", exc)
                break

            chunk_end = chunk_start - timedelta(seconds=1)
            await asyncio.sleep(8)

        return all_candles

    # ------------------------------------------------------------------
    # STOCKS — Polygon.io API
    # ------------------------------------------------------------------

    def _backfill_stocks(self, options):
        from trading_system.data.providers.polygon import PolygonProvider

        api_key = getattr(settings, "POLYGON_API_KEY", "")
        if not api_key:
            self.stdout.write(self.style.ERROR(
                "  [STOCKS] POLYGON_API_KEY not set — skipping.\n"
                "  Get a free key at https://polygon.io and add to .env"
            ))
            return

        symbols = options["symbols"] or getattr(
            settings, "STOCK_SYMBOLS",
            ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
             "META", "TSLA", "JPM", "V", "AVGO"],
        )
        tf = options["timeframe"]
        years = options["years"]

        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=years * 365)

        self.stdout.write(self.style.SUCCESS(f"\n  [STOCKS] Polygon.io API"))
        self.stdout.write(f"  Symbols: {len(symbols)} | Timeframe: {tf}")
        self.stdout.write(f"  Range: {start.date()} → {end.date()}")
        self.stdout.write(f"  Rate limit: 5 req/min (free tier)")
        self.stdout.write("")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        provider = PolygonProvider(api_key=api_key)
        total_saved = 0

        for si, symbol in enumerate(symbols, 1):
            self.stdout.write(f"  [{si}/{len(symbols)}] {symbol}...", ending="")
            try:
                candles = loop.run_until_complete(
                    provider.fetch_historical(symbol, tf, start, end)
                )
                if candles:
                    saved = self._bulk_save_candles(candles)
                    total_saved += saved
                    self.stdout.write(self.style.SUCCESS(f" {saved:,} candles"))
                else:
                    self.stdout.write(" no data")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f" FAILED: {exc}"))

        loop.run_until_complete(provider.close())
        loop.close()

        self.stdout.write(self.style.SUCCESS(
            f"\n  [STOCKS] Total: {total_saved:,} candles saved"
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _bulk_save(self, objects: list, batch_size: int = 5000) -> int:
        """Bulk insert MarketData objects, ignoring duplicates."""
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

    def _bulk_save_candles(self, candles, batch_size: int = 5000) -> int:
        """Convert Candle dataclass objects to MarketData and bulk save."""
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
        return self._bulk_save(objects, batch_size)

    @staticmethod
    def _generate_months(years: int) -> list[tuple[int, int]]:
        """Generate (year, month) tuples going back N years from now."""
        now = datetime.now(tz=timezone.utc)
        months = []
        for delta_months in range(years * 12):
            dt = now - timedelta(days=delta_months * 30.44)
            ym = (dt.year, dt.month)
            if ym not in months:
                months.append(ym)
        months.sort()
        return months
