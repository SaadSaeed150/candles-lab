"""
Shared fixtures and factories for the test suite.
"""

import pytest
from datetime import datetime, timezone

from trading_system.core.trader import PaperTrader, PositionSizing, Trade
from trading_system.core.risk import RiskConfig, RiskManager
from trading_system.core.engine import TradingEngine
from trading_system.core import registry
from trading_system.strategies.sample_strategy import SampleStrategy


@pytest.fixture
def candle():
    """A single OHLCV candle dict."""
    return {
        "symbol": "BTCUSDT",
        "exchange": "binance",
        "timeframe": "1m",
        "time": "2026-01-01T00:00:00+00:00",
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 1000,
        "extra": {},
    }


@pytest.fixture
def candle_series():
    """A series of candles with predictable prices for testing."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    prices = [
        (100, 105, 95, 98),
        (98, 103, 93, 95),
        (95, 100, 90, 92),
        (92, 97, 88, 115),
        (115, 120, 110, 118),
        (118, 123, 112, 108),
        (108, 113, 103, 105),
        (105, 110, 98, 97),
        (97, 102, 92, 94),
        (94, 99, 89, 112),
    ]
    candles = []
    for i, (o, h, l, c) in enumerate(prices):
        from datetime import timedelta
        t = base + timedelta(minutes=i)
        candles.append({
            "symbol": "BTCUSDT",
            "exchange": "binance",
            "timeframe": "1m",
            "time": t.isoformat(),
            "open": o, "high": h, "low": l, "close": c,
            "volume": 1000 + i * 100,
            "extra": {},
        })
    return candles


@pytest.fixture
def trader():
    """A PaperTrader with default settings and zero fees."""
    return PaperTrader(
        balance=10_000.0,
        commission_rate=0.0,
        slippage_rate=0.0,
        position_sizing=PositionSizing.ALL_IN,
    )


@pytest.fixture
def trader_with_fees():
    """A PaperTrader with realistic fees."""
    return PaperTrader(
        balance=10_000.0,
        commission_rate=0.001,
        slippage_rate=0.0,
        position_sizing=PositionSizing.ALL_IN,
    )


@pytest.fixture
def trader_percent_sizing():
    """A PaperTrader with percent-based position sizing."""
    return PaperTrader(
        balance=10_000.0,
        commission_rate=0.0,
        slippage_rate=0.0,
        position_sizing=PositionSizing.PERCENT,
        position_size_value=0.5,
    )


@pytest.fixture
def risk_config():
    """A strict risk configuration for testing."""
    return RiskConfig(
        max_position_pct=0.25,
        max_drawdown_pct=0.10,
        max_daily_loss_pct=0.03,
        max_open_positions=3,
        min_confidence=0.5,
    )


@pytest.fixture
def sample_strategy():
    return SampleStrategy()


@pytest.fixture
def engine(sample_strategy, trader):
    return TradingEngine(
        strategy=sample_strategy,
        trader=trader,
        initial_balance=10_000.0,
    )


@pytest.fixture
def buy_decision():
    return {"action": "BUY", "confidence": 0.8, "meta": {"reason": "test"}}


@pytest.fixture
def sell_decision():
    return {"action": "SELL", "confidence": 0.9, "meta": {"reason": "test"}}


@pytest.fixture
def hold_decision():
    return {"action": "HOLD", "confidence": 0.5, "meta": {}}


@pytest.fixture
def short_decision():
    return {"action": "SHORT", "confidence": 0.7, "meta": {"reason": "test"}}


@pytest.fixture
def sample_trades():
    """Pre-built trades for metrics testing."""
    return [
        Trade(symbol="BTC", side="LONG", entry_price=100, exit_price=110,
              quantity=10, pnl=100, commission=2, slippage=1,
              opened_at="2026-01-01T00:00:00", closed_at="2026-01-01T01:00:00"),
        Trade(symbol="BTC", side="LONG", entry_price=110, exit_price=105,
              quantity=10, pnl=-50, commission=2, slippage=1,
              opened_at="2026-01-02T00:00:00", closed_at="2026-01-02T01:00:00"),
        Trade(symbol="BTC", side="SHORT", entry_price=105, exit_price=95,
              quantity=10, pnl=100, commission=2, slippage=1,
              opened_at="2026-01-03T00:00:00", closed_at="2026-01-03T01:00:00"),
        Trade(symbol="BTC", side="LONG", entry_price=95, exit_price=100,
              quantity=10, pnl=50, commission=2, slippage=1,
              opened_at="2026-01-04T00:00:00", closed_at="2026-01-04T01:00:00"),
        Trade(symbol="BTC", side="SHORT", entry_price=100, exit_price=103,
              quantity=10, pnl=-30, commission=2, slippage=1,
              opened_at="2026-01-05T00:00:00", closed_at="2026-01-05T01:00:00"),
    ]
