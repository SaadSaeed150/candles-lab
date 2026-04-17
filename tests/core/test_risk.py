"""Tests for the RiskManager."""

import pytest
from trading_system.core.risk import RiskConfig, RiskManager


class TestMaxDrawdown:
    def test_rejects_when_drawdown_exceeds_limit(self, risk_config):
        rm = RiskManager(risk_config)
        decision = {"action": "BUY", "confidence": 0.8}
        context = {"balance": 8000, "equity": 8000, "open_positions": 0, "drawdown": 0.15}

        result = rm.validate(decision, context)

        assert result["action"] == "HOLD"
        assert result["meta"]["risk_reason"].startswith("max_drawdown")

    def test_allows_when_drawdown_within_limit(self, risk_config):
        rm = RiskManager(risk_config)
        decision = {"action": "BUY", "confidence": 0.8}
        context = {"balance": 9500, "equity": 9500, "open_positions": 0, "drawdown": 0.05}

        result = rm.validate(decision, context)

        assert result["action"] == "BUY"

    def test_kill_switch_activated_on_max_drawdown(self, risk_config):
        rm = RiskManager(risk_config)
        decision = {"action": "BUY", "confidence": 0.8}
        context = {"balance": 8000, "equity": 8000, "open_positions": 0, "drawdown": 0.15}

        rm.validate(decision, context)
        assert rm.state.is_killed

        result = rm.validate({"action": "BUY", "confidence": 0.9}, context)
        assert result["action"] == "HOLD"


class TestDailyLossLimit:
    def test_rejects_after_daily_loss_exceeded(self, risk_config):
        rm = RiskManager(risk_config)
        rm.state.daily_pnl = -350
        rm.state.current_date = "2026-01-01"

        decision = {"action": "BUY", "confidence": 0.8}
        context = {"balance": 9650, "equity": 9650, "open_positions": 0, "drawdown": 0.02, "date": "2026-01-01"}

        result = rm.validate(decision, context)
        assert result["action"] == "HOLD"
        assert "daily_loss" in result["meta"]["risk_reason"]

    def test_daily_loss_resets_on_new_day(self, risk_config):
        rm = RiskManager(risk_config)
        rm.state.daily_pnl = -350
        rm.state.current_date = "2026-01-01"

        decision = {"action": "BUY", "confidence": 0.8}
        context = {"balance": 9650, "equity": 9650, "open_positions": 0, "drawdown": 0.02, "date": "2026-01-02"}

        result = rm.validate(decision, context)
        assert result["action"] == "BUY"


class TestMaxPositions:
    def test_rejects_when_max_positions_reached(self, risk_config):
        rm = RiskManager(risk_config)
        decision = {"action": "BUY", "confidence": 0.8}
        context = {"balance": 9000, "equity": 9000, "open_positions": 3, "drawdown": 0}

        result = rm.validate(decision, context)
        assert result["action"] == "HOLD"
        assert "max_positions" in result["meta"]["risk_reason"]


class TestMinConfidence:
    def test_rejects_low_confidence(self, risk_config):
        rm = RiskManager(risk_config)
        decision = {"action": "BUY", "confidence": 0.3}
        context = {"balance": 10000, "equity": 10000, "open_positions": 0, "drawdown": 0}

        result = rm.validate(decision, context)
        assert result["action"] == "HOLD"
        assert "low_confidence" in result["meta"]["risk_reason"]

    def test_allows_high_confidence(self, risk_config):
        rm = RiskManager(risk_config)
        decision = {"action": "BUY", "confidence": 0.7}
        context = {"balance": 10000, "equity": 10000, "open_positions": 0, "drawdown": 0}

        result = rm.validate(decision, context)
        assert result["action"] == "BUY"


class TestHoldPassesThrough:
    def test_hold_is_never_rejected(self, risk_config):
        rm = RiskManager(risk_config)
        rm.state.is_killed = True

        decision = {"action": "HOLD"}
        context = {"balance": 5000, "equity": 5000, "open_positions": 5, "drawdown": 0.5}

        result = rm.validate(decision, context)
        assert result["action"] == "HOLD"


class TestReset:
    def test_reset_clears_state(self, risk_config):
        rm = RiskManager(risk_config)
        rm.state.is_killed = True
        rm.state.daily_pnl = -500
        rm.state.consecutive_losses = 5

        rm.reset()

        assert not rm.state.is_killed
        assert rm.state.daily_pnl == 0
        assert rm.state.consecutive_losses == 0
