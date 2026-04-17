"""
Trading engine — the central coordinator.

Receives market data, builds context, delegates to the active strategy,
validates through risk management, and forwards decisions to the trader.
Tracks equity snapshots and computes performance metrics at the end.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from trading_system.core.context import TradingContext
from trading_system.core.metrics import calculate_metrics
from trading_system.core.risk import RiskConfig, RiskManager
from trading_system.core.trader import PaperTrader
from trading_system.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "HOLD"}


def _validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Normalise and sanity-check a strategy's output."""
    action = decision.get("action", "HOLD").upper()
    if action not in VALID_ACTIONS:
        logger.warning("Invalid action '%s' — defaulting to HOLD", action)
        action = "HOLD"
    return {
        "action": action,
        "confidence": decision.get("confidence"),
        "stop_loss": decision.get("stop_loss"),
        "take_profit": decision.get("take_profit"),
        "meta": decision.get("meta", {}),
    }


class TradingEngine:
    """Orchestrates the data → strategy → risk → trader pipeline.

    Args:
        strategy:        An instance of a BaseStrategy subclass.
        trader:          A PaperTrader (or compatible) that executes decisions.
        risk_config:     Risk management configuration.
        initial_balance: Starting cash for the simulation.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        trader: PaperTrader | None = None,
        risk_config: RiskConfig | None = None,
        initial_balance: float = 10_000.0,
    ) -> None:
        self.strategy = strategy
        self.trader = trader or PaperTrader(balance=initial_balance)
        self.risk_manager = RiskManager(config=risk_config)
        self.initial_balance = initial_balance
        self._history: list[dict[str, Any]] = []
        self._results: list[dict[str, Any]] = []
        self._signals: list[dict[str, Any]] = []

    def tick(self, data: dict[str, Any]) -> dict[str, Any]:
        """Process a single data point through the full pipeline.

        Pipeline: data → context → strategy → validate → risk → trader
        """
        price = data.get("close", 0.0)
        context = self._build_context(price)

        decision = self.strategy.on_data(data, context)
        decision = _validate_decision(decision)

        self._signals.append({
            "timestamp": data.get("time"),
            "action": decision["action"],
            "price": price,
            "confidence": decision.get("confidence"),
            "stop_loss": decision.get("stop_loss"),
            "take_profit": decision.get("take_profit"),
            "meta": decision.get("meta", {}),
        })

        equity = self.trader.total_equity(price)
        risk_context = {
            "balance": self.trader.balance,
            "equity": equity,
            "open_positions": len(self.trader.positions),
            "drawdown": self._current_drawdown(price),
            "daily_pnl": self.risk_manager.state.daily_pnl,
            "date": data.get("time", "")[:10] if data.get("time") else "",
            "position_value": self.trader.balance if price > 0 else 0,
        }
        decision = self.risk_manager.validate(decision, risk_context)

        prev_trade_count = len(self.trader.trade_history)
        exec_result = self.trader.execute(decision, data)

        if len(self.trader.trade_history) > prev_trade_count:
            last_trade = self.trader.trade_history[-1]
            self.risk_manager.record_trade_result(last_trade.pnl)

        self.trader._record_equity(data.get("time", ""), price)

        self._history.append(data)
        result = {**decision, **exec_result, "data": data}
        self._results.append(result)
        return result

    def run(self, feed) -> list[dict[str, Any]]:
        """Consume an entire data feed and return all tick results."""
        results = []
        for data_point in feed:
            result = self.tick(data_point)
            results.append(result)
        return results

    def compute_metrics(self, periods_per_year: int = 252) -> dict[str, Any]:
        """Calculate performance metrics for the completed run."""
        first_price = self._history[0].get("close") if self._history else None
        last_price = self._history[-1].get("close") if self._history else None
        return calculate_metrics(
            trades=self.trader.trade_history,
            equity_snapshots=self.trader.equity_snapshots,
            initial_balance=self.initial_balance,
            periods_per_year=periods_per_year,
            first_price=first_price,
            last_price=last_price,
        )

    def _build_context(self, current_price: float) -> TradingContext:
        equity = self.trader.total_equity(current_price)
        return TradingContext(
            balance=self.trader.balance,
            equity=equity,
            position=self.trader.position,
            entry_price=self.trader.entry_price,
            open_positions=len(self.trader.positions),
            drawdown=self._current_drawdown(current_price),
            total_pnl=sum(t.pnl for t in self.trader.trade_history),
            trade_count=len(self.trader.trade_history),
            history=tuple(self._history[-100:]),
        )

    def _current_drawdown(self, current_price: float) -> float:
        equity = self.trader.total_equity(current_price)
        peak = self.trader._peak_equity
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - equity) / peak)

    @property
    def results(self) -> list[dict[str, Any]]:
        return list(self._results)

    @property
    def signals(self) -> list[dict[str, Any]]:
        return list(self._signals)

    @property
    def trade_history(self) -> list[dict]:
        return [
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "net_pnl": t.net_pnl,
                "commission": t.commission,
                "slippage": t.slippage,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
            }
            for t in self.trader.trade_history
        ]
