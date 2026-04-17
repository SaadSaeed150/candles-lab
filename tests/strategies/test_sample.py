"""Tests for the sample threshold strategy."""

import pytest
from trading_system.strategies.sample_strategy import SampleStrategy
from trading_system.core.context import TradingContext


class TestSampleStrategy:
    def test_buy_below_threshold(self):
        strategy = SampleStrategy()
        data = {"close": 90.0}
        context = TradingContext()

        result = strategy.on_data(data, context)

        assert result["action"] == "BUY"
        assert result["confidence"] == 0.7

    def test_sell_above_threshold(self):
        strategy = SampleStrategy()
        data = {"close": 115.0}
        context = TradingContext()

        result = strategy.on_data(data, context)

        assert result["action"] == "SELL"
        assert result["confidence"] == 0.8

    def test_hold_in_range(self):
        strategy = SampleStrategy()
        data = {"close": 105.0}
        context = TradingContext()

        result = strategy.on_data(data, context)

        assert result["action"] == "HOLD"
        assert result["confidence"] == 0.5

    def test_buy_at_exact_threshold(self):
        strategy = SampleStrategy()
        data = {"close": 100.0}
        context = TradingContext()

        result = strategy.on_data(data, context)
        assert result["action"] == "HOLD"

    def test_sell_at_exact_threshold(self):
        strategy = SampleStrategy()
        data = {"close": 110.0}
        context = TradingContext()

        result = strategy.on_data(data, context)
        assert result["action"] == "HOLD"

    def test_meta_includes_reason(self):
        strategy = SampleStrategy()
        data = {"close": 90.0}
        context = TradingContext()

        result = strategy.on_data(data, context)
        assert "reason" in result.get("meta", {})


class TestStrategyContract:
    def test_implements_base_strategy(self):
        from trading_system.strategies.base import BaseStrategy
        assert issubclass(SampleStrategy, BaseStrategy)

    def test_registered_in_registry(self):
        from trading_system.core import registry
        registry.load_defaults()
        assert "sample" in registry.available()

    def test_returns_required_keys(self):
        strategy = SampleStrategy()
        data = {"close": 105.0}
        context = TradingContext()

        result = strategy.on_data(data, context)
        assert "action" in result
