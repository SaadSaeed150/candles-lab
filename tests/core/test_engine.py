"""Tests for the TradingEngine pipeline."""

import pytest
from trading_system.core.engine import TradingEngine, _validate_decision
from trading_system.core.trader import PaperTrader
from trading_system.core.risk import RiskConfig
from trading_system.strategies.sample_strategy import SampleStrategy


class TestValidateDecision:
    def test_valid_actions_pass_through(self):
        for action in ["BUY", "SELL", "SHORT", "COVER", "HOLD"]:
            result = _validate_decision({"action": action})
            assert result["action"] == action

    def test_invalid_action_becomes_hold(self):
        result = _validate_decision({"action": "INVALID"})
        assert result["action"] == "HOLD"

    def test_missing_action_defaults_to_hold(self):
        result = _validate_decision({})
        assert result["action"] == "HOLD"

    def test_case_insensitive(self):
        result = _validate_decision({"action": "buy"})
        assert result["action"] == "BUY"

    def test_optional_fields_preserved(self):
        result = _validate_decision({
            "action": "BUY",
            "confidence": 0.9,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "meta": {"reason": "test"},
        })
        assert result["confidence"] == 0.9
        assert result["stop_loss"] == 95.0
        assert result["take_profit"] == 110.0
        assert result["meta"]["reason"] == "test"


class TestTickPipeline:
    def test_tick_returns_combined_result(self, engine, candle):
        result = engine.tick(candle)

        assert "action" in result
        assert "executed" in result
        assert "data" in result
        assert result["data"] == candle

    def test_tick_accumulates_history(self, engine, candle):
        engine.tick(candle)
        engine.tick(candle)
        engine.tick(candle)

        assert len(engine._history) == 3

    def test_tick_records_signals(self, engine, candle):
        engine.tick(candle)

        assert len(engine.signals) == 1
        assert engine.signals[0]["price"] == candle["close"]


class TestRunFeed:
    def test_run_processes_all_candles(self, engine, candle_series):
        results = engine.run(candle_series)

        assert len(results) == len(candle_series)
        assert len(engine.signals) == len(candle_series)

    def test_run_with_empty_feed(self, engine):
        results = engine.run([])
        assert results == []


class TestEngineWithRisk:
    def test_risk_integration_rejects_low_confidence(self):
        from trading_system.strategies.base import BaseStrategy
        from trading_system.core.context import TradingContext

        class LowConfStrategy(BaseStrategy):
            def on_data(self, data, context):
                return {"action": "BUY", "confidence": 0.1}

        risk_config = RiskConfig(min_confidence=0.5)
        engine = TradingEngine(
            strategy=LowConfStrategy(),
            risk_config=risk_config,
        )

        candle = {"symbol": "BTC", "close": 100, "time": "2026-01-01T00:00:00"}
        result = engine.tick(candle)

        assert result["executed"] == "HOLD"


class TestComputeMetrics:
    def test_metrics_available_after_run(self, engine, candle_series):
        engine.run(candle_series)
        metrics = engine.compute_metrics()

        assert "total_trades" in metrics
        assert "sharpe_ratio" in metrics
        assert "max_drawdown_pct" in metrics
        assert "win_rate" in metrics


class TestTradeHistory:
    def test_trade_history_has_required_fields(self, engine, candle_series):
        engine.run(candle_series)

        for trade in engine.trade_history:
            assert "symbol" in trade
            assert "side" in trade
            assert "entry_price" in trade
            assert "exit_price" in trade
            assert "pnl" in trade
            assert "net_pnl" in trade
            assert "commission" in trade
