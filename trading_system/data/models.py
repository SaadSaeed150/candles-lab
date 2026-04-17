"""
Django ORM models for persisting market data, trade records,
strategy runs, signals, equity curves, and user profiles.

Financial fields use DecimalField to avoid floating-point rounding errors.
MarketData and EquityCurve are designed to become TimescaleDB hypertables
via a later migration.
"""

from django.conf import settings
from django.db import models

TIMEFRAME_CHOICES = [
    ("1m", "1 Minute"),
    ("5m", "5 Minutes"),
    ("15m", "15 Minutes"),
    ("30m", "30 Minutes"),
    ("1h", "1 Hour"),
    ("4h", "4 Hours"),
    ("1d", "1 Day"),
    ("1w", "1 Week"),
]

EXCHANGE_CHOICES = [
    ("binance", "Binance"),
    ("twelvedata", "Twelve Data (Forex)"),
    ("polygon", "Polygon.io (US Stocks)"),
    ("finnhub", "Finnhub (US Stocks)"),
    ("alpaca", "Alpaca"),
    ("manual", "Manual / CSV Import"),
]

RUN_MODE_CHOICES = [
    ("backtest", "Backtest"),
    ("paper", "Paper Trading"),
    ("live", "Live Trading"),
]

SIDE_CHOICES = [
    ("LONG", "Long"),
    ("SHORT", "Short"),
]

ACTION_CHOICES = [
    ("BUY", "Buy"),
    ("SELL", "Sell"),
    ("HOLD", "Hold"),
]


class MarketData(models.Model):
    """A single OHLCV candle stored in the database.

    Will be converted to a TimescaleDB hypertable partitioned on `time`.
    """

    symbol = models.CharField(max_length=32, db_index=True)
    exchange = models.CharField(max_length=16, choices=EXCHANGE_CHOICES, default="binance", db_index=True)
    timeframe = models.CharField(max_length=4, choices=TIMEFRAME_CHOICES, default="1m", db_index=True)
    time = models.DateTimeField(db_index=True)
    open = models.DecimalField(max_digits=20, decimal_places=8)
    high = models.DecimalField(max_digits=20, decimal_places=8)
    low = models.DecimalField(max_digits=20, decimal_places=8)
    close = models.DecimalField(max_digits=20, decimal_places=8)
    volume = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["time"]
        unique_together = ("symbol", "exchange", "timeframe", "time")
        indexes = [
            models.Index(fields=["symbol", "timeframe", "time"]),
        ]

    def __str__(self) -> str:
        return f"{self.exchange}:{self.symbol} {self.timeframe} @ {self.time} C={self.close}"

    def to_feed_dict(self) -> dict:
        """Convert to the dict format the engine expects."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "time": self.time.isoformat(),
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
            "extra": self.extra or {},
        }


class TradeRecord(models.Model):
    """Persisted record of a completed round-trip trade."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trades",
        null=True,
        blank=True,
    )
    run = models.ForeignKey(
        "StrategyRun",
        on_delete=models.CASCADE,
        related_name="trades",
        null=True,
        blank=True,
    )
    symbol = models.CharField(max_length=32, db_index=True)
    exchange = models.CharField(max_length=16, choices=EXCHANGE_CHOICES, default="binance")
    side = models.CharField(max_length=8, choices=SIDE_CHOICES)
    entry_price = models.DecimalField(max_digits=20, decimal_places=8)
    exit_price = models.DecimalField(max_digits=20, decimal_places=8)
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    pnl = models.DecimalField(max_digits=20, decimal_places=8)
    commission = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    slippage = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-closed_at"]

    def __str__(self) -> str:
        return f"{self.side} {self.symbol} PnL={self.pnl:.2f}"

    @property
    def net_pnl(self) -> float:
        """PnL after commission and slippage."""
        return float(self.pnl - self.commission - self.slippage)


class StrategyRun(models.Model):
    """Tracks an individual backtest, paper trading, or live trading session."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="strategy_runs",
        null=True,
        blank=True,
    )
    strategy_name = models.CharField(max_length=64, db_index=True)
    mode = models.CharField(max_length=16, choices=RUN_MODE_CHOICES)
    symbol = models.CharField(max_length=32, db_index=True)
    exchange = models.CharField(max_length=16, choices=EXCHANGE_CHOICES, default="binance")
    timeframe = models.CharField(max_length=4, choices=TIMEFRAME_CHOICES, default="1m")
    config = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("pending", "Pending"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    initial_balance = models.DecimalField(max_digits=20, decimal_places=8, default=10_000)
    final_balance = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.strategy_name} ({self.mode}) {self.symbol} @ {self.started_at:%Y-%m-%d %H:%M}"


class StrategySignal(models.Model):
    """Logs every decision a strategy makes on every tick.

    Useful for debugging, replay, and comparing strategies.
    """

    run = models.ForeignKey(StrategyRun, on_delete=models.CASCADE, related_name="signals")
    timestamp = models.DateTimeField(db_index=True)
    action = models.CharField(max_length=8, choices=ACTION_CHOICES)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    confidence = models.FloatField(null=True, blank=True)
    stop_loss = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["run", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} @ {self.price} ({self.timestamp})"


class EquityCurve(models.Model):
    """Time-series snapshot of portfolio value during a strategy run.

    Will be converted to a TimescaleDB hypertable partitioned on `timestamp`.
    """

    run = models.ForeignKey(StrategyRun, on_delete=models.CASCADE, related_name="equity_curve")
    timestamp = models.DateTimeField(db_index=True)
    balance = models.DecimalField(max_digits=20, decimal_places=8)
    unrealised_pnl = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    total_equity = models.DecimalField(max_digits=20, decimal_places=8)
    drawdown = models.FloatField(default=0.0)

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["run", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"Run {self.run_id} equity={self.total_equity} @ {self.timestamp}"


class OrderBookSnapshot(models.Model):
    """Point-in-time snapshot of the order book (top N bids/asks).

    Collected every 1 minute via REST /api/v3/depth.
    """

    symbol = models.CharField(max_length=32, db_index=True)
    exchange = models.CharField(max_length=16, choices=EXCHANGE_CHOICES, default="binance")
    timestamp = models.DateTimeField(db_index=True)

    bids = models.JSONField(default=list)
    asks = models.JSONField(default=list)

    best_bid_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    best_bid_qty = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    best_ask_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    best_ask_qty = models.DecimalField(max_digits=20, decimal_places=8, default=0)

    spread = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    spread_pct = models.FloatField(default=0)
    mid_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)

    total_bid_qty = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    total_ask_qty = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    book_imbalance = models.FloatField(default=0)

    last_update_id = models.BigIntegerField(default=0)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["symbol", "timestamp"]),
            models.Index(fields=["symbol", "exchange", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.symbol} depth mid={self.mid_price} spread={self.spread_pct:.4f}% @ {self.timestamp}"


class TickerSnapshot(models.Model):
    """24h rolling ticker statistics snapshot.

    Collected every 1 minute from WebSocket @ticker stream.
    """

    symbol = models.CharField(max_length=32, db_index=True)
    exchange = models.CharField(max_length=16, choices=EXCHANGE_CHOICES, default="binance")
    timestamp = models.DateTimeField(db_index=True)

    price_change = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    price_change_pct = models.FloatField(default=0)
    weighted_avg_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    prev_close = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    last_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    volume = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    quote_volume = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    open_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    high_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    low_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    trade_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["symbol", "timestamp"]),
            models.Index(fields=["symbol", "exchange", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.symbol} 24h {self.price_change_pct:+.2f}% last={self.last_price} @ {self.timestamp}"


class BookTickerSnapshot(models.Model):
    """Best bid/ask snapshot.

    Collected every 1 minute from WebSocket @bookTicker stream.
    """

    symbol = models.CharField(max_length=32, db_index=True)
    exchange = models.CharField(max_length=16, choices=EXCHANGE_CHOICES, default="binance")
    timestamp = models.DateTimeField(db_index=True)

    best_bid_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    best_bid_qty = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    best_ask_price = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    best_ask_qty = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    spread = models.DecimalField(max_digits=20, decimal_places=8, default=0)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["symbol", "timestamp"]),
            models.Index(fields=["symbol", "exchange", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.symbol} bid={self.best_bid_price} ask={self.best_ask_price} @ {self.timestamp}"


class UserProfile(models.Model):
    """Trading-specific profile extending Django's auth User."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    binance_api_key = models.CharField(max_length=256, blank=True, default="")
    binance_api_secret = models.CharField(max_length=256, blank=True, default="")
    alpaca_api_key = models.CharField(max_length=256, blank=True, default="")
    alpaca_api_secret = models.CharField(max_length=256, blank=True, default="")

    default_balance = models.DecimalField(max_digits=20, decimal_places=2, default=10_000)
    risk_tolerance = models.CharField(
        max_length=16,
        choices=[
            ("conservative", "Conservative"),
            ("moderate", "Moderate"),
            ("aggressive", "Aggressive"),
        ],
        default="moderate",
    )
    timezone = models.CharField(max_length=64, default="UTC")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile: {self.user.username}"
