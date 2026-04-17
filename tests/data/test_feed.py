"""Tests for data feed generators."""

import pytest
from datetime import datetime, timedelta
from trading_system.data.feed import generate_feed


class TestSyntheticFeed:
    def test_generates_correct_count(self):
        candles = list(generate_feed(num_points=20))
        assert len(candles) == 20

    def test_candle_has_required_fields(self):
        candle = next(generate_feed(num_points=1))

        assert "symbol" in candle
        assert "time" in candle
        assert "open" in candle
        assert "high" in candle
        assert "low" in candle
        assert "close" in candle
        assert "volume" in candle

    def test_ohlcv_constraints(self):
        for candle in generate_feed(num_points=100):
            assert candle["high"] >= candle["open"]
            assert candle["high"] >= candle["close"]
            assert candle["low"] <= candle["open"]
            assert candle["low"] <= candle["close"]
            assert candle["low"] > 0
            assert candle["volume"] > 0

    def test_custom_symbol(self):
        candle = next(generate_feed(symbol="ETHUSDT", num_points=1))
        assert candle["symbol"] == "ETHUSDT"

    def test_custom_start_price(self):
        candles = list(generate_feed(start_price=50000.0, num_points=1, volatility=0))
        assert candles[0]["open"] == 50000.0

    def test_time_increments(self):
        candles = list(generate_feed(num_points=5, interval=timedelta(minutes=5)))
        times = [candle["time"] for candle in candles]
        for i in range(1, len(times)):
            t1 = datetime.fromisoformat(times[i - 1])
            t2 = datetime.fromisoformat(times[i])
            assert (t2 - t1) == timedelta(minutes=5)

    def test_zero_volatility_produces_flat_prices(self):
        candles = list(generate_feed(start_price=100, num_points=10, volatility=0))
        for c in candles:
            assert c["open"] == 100.0
            assert c["close"] == 100.0

    def test_is_iterator(self):
        feed = generate_feed(num_points=5)
        assert hasattr(feed, "__iter__")
        assert hasattr(feed, "__next__")


class TestCSVProvider:
    def test_csv_loader_import(self):
        from trading_system.data.providers.csv_loader import CSVProvider
        provider = CSVProvider(file_path="/nonexistent.csv", symbol="TEST")
        assert provider.name == "csv"
        assert provider._symbol == "TEST"

    def test_csv_file_not_found(self):
        from trading_system.data.providers.csv_loader import CSVProvider
        provider = CSVProvider(file_path="/nonexistent.csv")

        with pytest.raises(FileNotFoundError):
            provider._load()
