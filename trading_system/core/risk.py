"""
Risk manager — validates and modifies trade decisions before execution.

Enforces portfolio-level risk constraints:
    - Maximum position size (% of equity per trade)
    - Maximum drawdown kill switch
    - Daily loss limit
    - Maximum concurrent open positions
    - Minimum confidence threshold
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Configuration for risk management rules.

    All percentage values are expressed as fractions (0.02 = 2%).
    Set a value to None or 0 to disable that rule.
    """

    max_position_pct: float = 0.25
    max_drawdown_pct: float = 0.20
    max_daily_loss_pct: float = 0.05
    max_open_positions: int = 5
    min_confidence: float = 0.0
    cooldown_after_loss: int = 0


@dataclass
class RiskState:
    """Tracks runtime risk state across ticks."""

    peak_equity: float = 0.0
    daily_pnl: float = 0.0
    current_date: str = ""
    consecutive_losses: int = 0
    ticks_since_last_loss: int = 0
    is_killed: bool = False
    kill_reason: str = ""


class RiskManager:
    """Evaluates risk rules and modifies or rejects decisions.

    Sits between the strategy and the trader in the pipeline:
        strategy → RiskManager.validate() → trader.execute()
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self.state = RiskState()

    def validate(
        self,
        decision: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate a decision against risk rules.

        Args:
            decision: The strategy's output (action, confidence, etc.)
            context:  Current state — must include:
                        balance, equity, open_positions (count),
                        drawdown, daily_pnl

        Returns:
            Modified decision dict. action may be changed to HOLD
            with a meta.risk_reason explaining why.
        """
        self.state.ticks_since_last_loss += 1

        if self.state.is_killed:
            return self._reject(decision, f"risk_kill_switch: {self.state.kill_reason}")

        action = decision.get("action", "HOLD").upper()
        if action == "HOLD":
            return decision

        equity = context.get("equity", context.get("balance", 0))
        balance = context.get("balance", 0)
        drawdown = context.get("drawdown", 0)
        open_positions = context.get("open_positions", 0)
        today = context.get("date", "")

        if today and today != self.state.current_date:
            self.state.daily_pnl = 0.0
            self.state.current_date = today

        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

        if action in ("BUY", "SHORT"):
            position_value = context.get("position_value", 0)
            reason = self._check_entry_rules(
                decision, equity, balance, drawdown, open_positions, position_value,
            )
            if reason:
                return self._reject(decision, reason)

        return decision

    def record_trade_result(self, pnl: float) -> None:
        """Update risk state after a trade completes."""
        self.state.daily_pnl += pnl

        if pnl < 0:
            self.state.consecutive_losses += 1
            self.state.ticks_since_last_loss = 0
        else:
            self.state.consecutive_losses = 0

    def _check_entry_rules(
        self,
        decision: dict[str, Any],
        equity: float,
        balance: float,
        drawdown: float,
        open_positions: int,
        position_value: float = 0,
    ) -> str | None:
        """Check all entry rules. Returns rejection reason or None."""
        cfg = self.config

        if cfg.max_position_pct and equity > 0 and position_value > 0:
            pct = position_value / equity
            if pct > cfg.max_position_pct:
                return f"position_too_large ({pct:.1%} > {cfg.max_position_pct:.1%})"

        if cfg.max_drawdown_pct and drawdown >= cfg.max_drawdown_pct:
            self.state.is_killed = True
            self.state.kill_reason = f"drawdown {drawdown:.1%} >= limit {cfg.max_drawdown_pct:.1%}"
            return f"max_drawdown_exceeded ({drawdown:.1%})"

        if cfg.max_daily_loss_pct and equity > 0:
            daily_loss_pct = abs(self.state.daily_pnl) / equity if self.state.daily_pnl < 0 else 0
            if daily_loss_pct >= cfg.max_daily_loss_pct:
                return f"daily_loss_limit ({daily_loss_pct:.1%})"

        if cfg.max_open_positions and open_positions >= cfg.max_open_positions:
            return f"max_positions ({open_positions}/{cfg.max_open_positions})"

        confidence = decision.get("confidence", 1.0)
        if confidence is not None and cfg.min_confidence and confidence < cfg.min_confidence:
            return f"low_confidence ({confidence:.2f} < {cfg.min_confidence:.2f})"

        if cfg.cooldown_after_loss and self.state.ticks_since_last_loss < cfg.cooldown_after_loss:
            if self.state.consecutive_losses > 0:
                return f"loss_cooldown ({self.state.ticks_since_last_loss}/{cfg.cooldown_after_loss})"

        return None

    @staticmethod
    def _reject(decision: dict[str, Any], reason: str) -> dict[str, Any]:
        """Convert a decision to HOLD with a risk rejection reason."""
        logger.info("Risk rejected %s: %s", decision.get("action"), reason)
        meta = dict(decision.get("meta", {}))
        meta["risk_rejected"] = True
        meta["risk_reason"] = reason
        meta["original_action"] = decision.get("action")
        return {
            **decision,
            "action": "HOLD",
            "meta": meta,
        }

    def reset(self) -> None:
        """Reset risk state for a new session."""
        self.state = RiskState()
