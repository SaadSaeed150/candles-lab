"""
Paper trader — executes BUY/SELL/SHORT/COVER decisions against a virtual balance.

Supports:
    - Long and short positions
    - Configurable commission and slippage
    - Configurable position sizing (fixed, percent, all-in)
    - Stop-loss and take-profit auto-execution
    - Multiple concurrent positions (portfolio mode)
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PositionSizing(Enum):
    ALL_IN = "all_in"
    FIXED_AMOUNT = "fixed_amount"
    PERCENT = "percent"


@dataclass
class Trade:
    """Record of a single completed round-trip trade."""

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    commission: float
    slippage: float
    opened_at: str
    closed_at: str
    meta: dict = field(default_factory=dict)

    @property
    def net_pnl(self) -> float:
        return self.pnl - self.commission - self.slippage


@dataclass
class OpenPosition:
    """A currently open position."""

    symbol: str
    side: str
    entry_price: float
    quantity: float
    opened_at: str
    stop_loss: float | None = None
    take_profit: float | None = None
    meta: dict = field(default_factory=dict)

    def unrealised_pnl(self, current_price: float) -> float:
        if self.side == "LONG":
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price


@dataclass
class PaperTrader:
    """Simulated trader with realistic execution modelling.

    Args:
        balance:            Starting cash.
        commission_rate:    Per-trade commission as a fraction (e.g. 0.001 = 0.1%).
        slippage_rate:      Max random slippage as a fraction (e.g. 0.0005 = 0.05%).
        position_sizing:    How to size positions (all_in, fixed_amount, percent).
        position_size_value: Value used by the sizing method (amount or percent 0-1).
        max_positions:      Maximum concurrent open positions.
    """

    balance: float = 10_000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005
    position_sizing: PositionSizing = PositionSizing.ALL_IN
    position_size_value: float = 0.0
    max_positions: int = 1

    positions: dict[str, OpenPosition] = field(default_factory=dict)
    trade_history: list[Trade] = field(default_factory=list)
    _peak_equity: float = field(default=0.0, init=False)
    _equity_snapshots: list[dict] = field(default_factory=list, init=False)

    def __post_init__(self):
        self._peak_equity = self.balance

    # -- Public interface -----------------------------------------------------

    def execute(self, decision: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Apply a strategy decision to the current state."""
        price = data.get("close", 0.0)
        symbol = data.get("symbol", "UNKNOWN")
        timestamp = data.get("time", datetime.utcnow().isoformat())

        self._check_stop_loss_take_profit(symbol, price, timestamp)

        action = decision.get("action", "HOLD").upper()

        if action == "BUY":
            return self._open_position(
                "LONG", price, symbol, timestamp, decision
            )
        elif action == "SELL":
            if symbol in self.positions and self.positions[symbol].side == "LONG":
                return self._close_position(symbol, price, timestamp)
            elif symbol not in self.positions:
                return self._open_position(
                    "SHORT", price, symbol, timestamp, decision
                )
            else:
                return self._close_position(symbol, price, timestamp)
        elif action == "SHORT":
            return self._open_position(
                "SHORT", price, symbol, timestamp, decision
            )
        elif action == "COVER":
            if symbol in self.positions and self.positions[symbol].side == "SHORT":
                return self._close_position(symbol, price, timestamp)
            return {"executed": "SKIP", "reason": "no_short_position", "balance": self.balance}

        self._record_equity(timestamp, price)
        return {"executed": "HOLD", "balance": self.balance}

    # -- Position sizing ------------------------------------------------------

    def _calculate_quantity(self, price: float) -> float:
        """Determine how many units to buy/short based on sizing method."""
        if self.position_sizing == PositionSizing.ALL_IN:
            return self.balance / price
        elif self.position_sizing == PositionSizing.FIXED_AMOUNT:
            amount = min(self.position_size_value, self.balance)
            return amount / price
        elif self.position_sizing == PositionSizing.PERCENT:
            pct = max(0.0, min(1.0, self.position_size_value))
            amount = self.balance * pct
            return amount / price
        return self.balance / price

    # -- Slippage and commission ----------------------------------------------

    def _apply_slippage(self, price: float, side: str) -> float:
        """Simulate slippage — price moves against you."""
        if self.slippage_rate <= 0:
            return price
        slip = price * random.uniform(0, self.slippage_rate)
        if side == "LONG":
            return price + slip
        return price - slip

    def _calculate_commission(self, price: float, quantity: float) -> float:
        return price * quantity * self.commission_rate

    # -- Open / close positions -----------------------------------------------

    def _open_position(
        self,
        side: str,
        price: float,
        symbol: str,
        timestamp: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        if symbol in self.positions:
            logger.info("Already in a %s position for %s — skipping", self.positions[symbol].side, symbol)
            return {"executed": "SKIP", "reason": "position_exists", "balance": self.balance}

        if len(self.positions) >= self.max_positions:
            logger.info("Max positions (%d) reached — skipping", self.max_positions)
            return {"executed": "SKIP", "reason": "max_positions", "balance": self.balance}

        fill_price = self._apply_slippage(price, side)
        quantity = self._calculate_quantity(fill_price)

        if quantity <= 0:
            return {"executed": "SKIP", "reason": "insufficient_balance", "balance": self.balance}

        commission = self._calculate_commission(fill_price, quantity)
        cost = (fill_price * quantity) + commission
        if cost > self.balance and side == "LONG":
            quantity = (self.balance - commission) / fill_price
            commission = self._calculate_commission(fill_price, quantity)
            cost = (fill_price * quantity) + commission

        self.balance -= cost if side == "LONG" else commission

        pos = OpenPosition(
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            quantity=quantity,
            opened_at=timestamp,
            stop_loss=decision.get("stop_loss"),
            take_profit=decision.get("take_profit"),
            meta=decision.get("meta", {}),
        )
        self.positions[symbol] = pos

        logger.info(
            "OPENED %s %s %.4f units @ %.2f (fill=%.2f, comm=%.4f)",
            side, symbol, quantity, price, fill_price, commission,
        )
        self._record_equity(timestamp, price)
        return {
            "executed": action_for_side(side),
            "side": side,
            "entry_price": fill_price,
            "quantity": quantity,
            "commission": commission,
            "balance": self.balance,
        }

    def _close_position(
        self, symbol: str, price: float, timestamp: str
    ) -> dict[str, Any]:
        if symbol not in self.positions:
            logger.info("No open position for %s — skipping", symbol)
            return {"executed": "SKIP", "reason": "no_position", "balance": self.balance}

        pos = self.positions[symbol]
        fill_price = self._apply_slippage(price, "SHORT" if pos.side == "LONG" else "LONG")
        commission = self._calculate_commission(fill_price, pos.quantity)

        if pos.side == "LONG":
            pnl = (fill_price - pos.entry_price) * pos.quantity
            proceeds = fill_price * pos.quantity
        else:
            pnl = (pos.entry_price - fill_price) * pos.quantity
            proceeds = pos.entry_price * pos.quantity + pnl

        self.balance += proceeds - commission

        entry_commission = self._calculate_commission(pos.entry_price, pos.quantity)
        total_slippage = abs(fill_price - price) * pos.quantity

        trade = Trade(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            quantity=pos.quantity,
            pnl=pnl,
            commission=entry_commission + commission,
            slippage=total_slippage,
            opened_at=pos.opened_at,
            closed_at=timestamp,
            meta=pos.meta,
        )
        self.trade_history.append(trade)

        logger.info(
            "CLOSED %s %s %.4f units @ %.2f (fill=%.2f) | PnL: %.2f (net: %.2f)",
            pos.side, symbol, pos.quantity, price, fill_price, pnl, trade.net_pnl,
        )

        del self.positions[symbol]
        self._record_equity(timestamp, price)
        return {
            "executed": "SELL" if pos.side == "LONG" else "COVER",
            "side": pos.side,
            "exit_price": fill_price,
            "pnl": pnl,
            "net_pnl": trade.net_pnl,
            "commission": commission,
            "balance": self.balance,
        }

    # -- Stop-loss / take-profit ----------------------------------------------

    def _check_stop_loss_take_profit(
        self, symbol: str, price: float, timestamp: str
    ) -> None:
        """Auto-close positions that hit their SL or TP levels."""
        symbols_to_close: list[tuple[str, str]] = []

        for sym, pos in self.positions.items():
            if pos.side == "LONG":
                if pos.stop_loss and price <= pos.stop_loss:
                    symbols_to_close.append((sym, "stop_loss"))
                elif pos.take_profit and price >= pos.take_profit:
                    symbols_to_close.append((sym, "take_profit"))
            elif pos.side == "SHORT":
                if pos.stop_loss and price >= pos.stop_loss:
                    symbols_to_close.append((sym, "stop_loss"))
                elif pos.take_profit and price <= pos.take_profit:
                    symbols_to_close.append((sym, "take_profit"))

        for sym, reason in symbols_to_close:
            logger.info("Auto-closing %s for %s: %s triggered at %.2f", self.positions[sym].side, sym, reason, price)
            self._close_position(sym, price, timestamp)

    # -- Equity tracking ------------------------------------------------------

    def _record_equity(self, timestamp: str, current_price: float) -> None:
        equity = self.total_equity(current_price)
        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown = (self._peak_equity - equity) / self._peak_equity if self._peak_equity > 0 else 0.0

        self._equity_snapshots.append({
            "timestamp": timestamp,
            "balance": self.balance,
            "unrealised_pnl": self.total_unrealised_pnl(current_price),
            "total_equity": equity,
            "drawdown": drawdown,
        })

    def total_unrealised_pnl(self, current_price: float) -> float:
        return sum(pos.unrealised_pnl(current_price) for pos in self.positions.values())

    def total_equity(self, current_price: float) -> float:
        return self.balance + sum(
            pos.market_value(current_price) for pos in self.positions.values()
        )

    # -- Backward-compatible properties ---------------------------------------

    @property
    def position(self) -> str | None:
        """First open position's side (backward compat with old engine)."""
        if not self.positions:
            return None
        return next(iter(self.positions.values())).side

    @property
    def entry_price(self) -> float | None:
        if not self.positions:
            return None
        return next(iter(self.positions.values())).entry_price

    @property
    def quantity(self) -> float:
        if not self.positions:
            return 0.0
        return next(iter(self.positions.values())).quantity

    @property
    def equity_snapshots(self) -> list[dict]:
        return list(self._equity_snapshots)

    def snapshot(self) -> dict[str, Any]:
        """Return current state as a JSON-serializable dict."""
        return {
            "balance": self.balance,
            "open_positions": {
                sym: {
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "quantity": pos.quantity,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit,
                }
                for sym, pos in self.positions.items()
            },
            "trade_count": len(self.trade_history),
            "total_pnl": sum(t.pnl for t in self.trade_history),
            "total_net_pnl": sum(t.net_pnl for t in self.trade_history),
            "total_commission": sum(t.commission for t in self.trade_history),
        }


def action_for_side(side: str) -> str:
    return "BUY" if side == "LONG" else "SHORT"
