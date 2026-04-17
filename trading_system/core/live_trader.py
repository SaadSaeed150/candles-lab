"""
Live trader — executes real orders via exchange APIs.

Same interface as PaperTrader so the engine can swap between them
via dependency injection. Wraps exchange-specific order placement
with safety checks and order tracking.

IMPORTANT: This module places real orders. Use with extreme caution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from trading_system.core.trader import OpenPosition, Trade

logger = logging.getLogger(__name__)


@dataclass
class LiveTrader:
    """Executes trades against a real exchange.

    Currently supports Binance and Alpaca. Uses the same Trade/OpenPosition
    dataclasses as PaperTrader for compatibility.

    Args:
        exchange:       "binance" or "alpaca".
        api_key:        Exchange API key.
        api_secret:     Exchange API secret.
        paper_mode:     If True, use exchange's paper/testnet (Alpaca paper, Binance testnet).
        require_confirmation: If True, log the order but don't execute without explicit confirm.
        max_positions:  Maximum concurrent positions allowed.
    """

    exchange: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    paper_mode: bool = True
    require_confirmation: bool = True
    max_positions: int = 1

    balance: float = 0.0
    positions: dict[str, OpenPosition] = field(default_factory=dict)
    trade_history: list[Trade] = field(default_factory=list)
    _peak_equity: float = field(default=0.0, init=False)
    _equity_snapshots: list[dict] = field(default_factory=list, init=False)
    _client: Any = field(default=None, init=False, repr=False)
    _kill_switch: bool = field(default=False, init=False)

    def execute(self, decision: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Apply a strategy decision by placing a real order."""
        if self._kill_switch:
            logger.warning("Kill switch active — all trading halted")
            return {"executed": "KILLED", "balance": self.balance}

        action = decision.get("action", "HOLD").upper()
        price = data.get("close", 0.0)
        symbol = data.get("symbol", "UNKNOWN")
        timestamp = data.get("time", datetime.utcnow().isoformat())

        if action == "HOLD":
            return {"executed": "HOLD", "balance": self.balance}

        if self.require_confirmation:
            logger.warning(
                "LIVE ORDER PENDING CONFIRMATION: %s %s @ ~%.2f | Set require_confirmation=False to auto-execute",
                action, symbol, price,
            )
            return {
                "executed": "PENDING_CONFIRMATION",
                "action": action,
                "symbol": symbol,
                "price": price,
                "balance": self.balance,
            }

        if action in ("BUY", "SHORT"):
            return self._place_entry_order(action, symbol, price, timestamp, decision)
        elif action in ("SELL", "COVER"):
            return self._place_exit_order(action, symbol, price, timestamp)

        return {"executed": "HOLD", "balance": self.balance}

    def _place_entry_order(
        self,
        action: str,
        symbol: str,
        price: float,
        timestamp: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Place an entry order on the exchange."""
        if symbol in self.positions:
            return {"executed": "SKIP", "reason": "position_exists", "balance": self.balance}

        if len(self.positions) >= self.max_positions:
            return {"executed": "SKIP", "reason": "max_positions", "balance": self.balance}

        side = "LONG" if action == "BUY" else "SHORT"

        try:
            order_result = self._submit_order(symbol, side, price)
        except Exception as exc:
            logger.error("Order failed for %s %s: %s", action, symbol, exc)
            return {"executed": "ERROR", "error": str(exc), "balance": self.balance}

        fill_price = order_result.get("fill_price", price)
        quantity = order_result.get("quantity", 0)
        commission = order_result.get("commission", 0)

        pos = OpenPosition(
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            quantity=quantity,
            opened_at=timestamp,
            stop_loss=decision.get("stop_loss"),
            take_profit=decision.get("take_profit"),
        )
        self.positions[symbol] = pos
        self.balance -= (fill_price * quantity + commission) if side == "LONG" else commission

        logger.info("LIVE %s %s %.4f @ %.2f (order_id: %s)", side, symbol, quantity, fill_price, order_result.get("order_id"))

        return {
            "executed": action,
            "side": side,
            "entry_price": fill_price,
            "quantity": quantity,
            "commission": commission,
            "order_id": order_result.get("order_id"),
            "balance": self.balance,
        }

    def _place_exit_order(
        self,
        action: str,
        symbol: str,
        price: float,
        timestamp: str,
    ) -> dict[str, Any]:
        """Place an exit order on the exchange."""
        if symbol not in self.positions:
            return {"executed": "SKIP", "reason": "no_position", "balance": self.balance}

        pos = self.positions[symbol]

        try:
            order_result = self._submit_order(symbol, "CLOSE", price, quantity=pos.quantity)
        except Exception as exc:
            logger.error("Exit order failed for %s: %s", symbol, exc)
            return {"executed": "ERROR", "error": str(exc), "balance": self.balance}

        fill_price = order_result.get("fill_price", price)
        commission = order_result.get("commission", 0)

        if pos.side == "LONG":
            pnl = (fill_price - pos.entry_price) * pos.quantity
            proceeds = fill_price * pos.quantity
        else:
            pnl = (pos.entry_price - fill_price) * pos.quantity
            proceeds = pos.entry_price * pos.quantity + pnl

        self.balance += proceeds - commission

        trade = Trade(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            quantity=pos.quantity,
            pnl=pnl,
            commission=commission,
            slippage=abs(fill_price - price) * pos.quantity,
            opened_at=pos.opened_at,
            closed_at=timestamp,
        )
        self.trade_history.append(trade)
        del self.positions[symbol]

        logger.info("LIVE CLOSED %s %s PnL=%.2f (order_id: %s)", pos.side, symbol, pnl, order_result.get("order_id"))

        return {
            "executed": action,
            "side": pos.side,
            "exit_price": fill_price,
            "pnl": pnl,
            "commission": commission,
            "order_id": order_result.get("order_id"),
            "balance": self.balance,
        }

    def _submit_order(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float | None = None,
    ) -> dict[str, Any]:
        """Submit an order to the exchange. Override for specific exchange logic."""
        if self.exchange == "binance":
            return self._binance_order(symbol, side, price, quantity)
        elif self.exchange == "alpaca":
            return self._alpaca_order(symbol, side, price, quantity)
        raise ValueError(f"Unsupported exchange: {self.exchange}")

    def _binance_order(
        self, symbol: str, side: str, price: float, quantity: float | None
    ) -> dict[str, Any]:
        """Place a market order on Binance."""
        from binance.client import Client

        if self._client is None:
            self._client = Client(
                self.api_key,
                self.api_secret,
                testnet=self.paper_mode,
            )

        if side == "CLOSE":
            order = self._client.create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=quantity,
            )
        elif side == "LONG":
            qty = quantity or (self.balance * 0.95) / price
            order = self._client.create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=round(qty, 6),
            )
        else:
            raise ValueError(f"Binance short selling not implemented yet: {side}")

        fills = order.get("fills", [])
        fill_price = float(fills[0]["price"]) if fills else price
        fill_qty = float(order.get("executedQty", quantity or 0))
        commission = sum(float(f.get("commission", 0)) for f in fills)

        return {
            "order_id": order.get("orderId"),
            "fill_price": fill_price,
            "quantity": fill_qty,
            "commission": commission,
        }

    def _alpaca_order(
        self, symbol: str, side: str, price: float, quantity: float | None
    ) -> dict[str, Any]:
        """Place a market order on Alpaca."""
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        if self._client is None:
            self._client = TradingClient(
                self.api_key,
                self.api_secret,
                paper=self.paper_mode,
            )

        if side in ("LONG", "CLOSE"):
            alpaca_side = OrderSide.BUY if side == "LONG" else OrderSide.SELL
        else:
            alpaca_side = OrderSide.SELL

        qty = quantity or int((self.balance * 0.95) / price)
        if qty <= 0:
            raise ValueError("Insufficient balance for order")

        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=alpaca_side,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)

        return {
            "order_id": str(order.id),
            "fill_price": float(order.filled_avg_price or price),
            "quantity": float(order.filled_qty or qty),
            "commission": 0,
        }

    def activate_kill_switch(self) -> None:
        """Emergency stop — halt all trading immediately."""
        self._kill_switch = True
        logger.critical("KILL SWITCH ACTIVATED — all trading halted")

    def deactivate_kill_switch(self) -> None:
        self._kill_switch = False
        logger.warning("Kill switch deactivated — trading resumed")

    # -- Compatibility properties (match PaperTrader interface) ----------------

    @property
    def position(self) -> str | None:
        if not self.positions:
            return None
        return next(iter(self.positions.values())).side

    @property
    def entry_price(self) -> float | None:
        if not self.positions:
            return None
        return next(iter(self.positions.values())).entry_price

    @property
    def equity_snapshots(self) -> list[dict]:
        return list(self._equity_snapshots)

    def total_equity(self, current_price: float) -> float:
        return self.balance + sum(
            pos.market_value(current_price) for pos in self.positions.values()
        )

    def total_unrealised_pnl(self, current_price: float) -> float:
        return sum(pos.unrealised_pnl(current_price) for pos in self.positions.values())

    def snapshot(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "exchange": self.exchange,
            "paper_mode": self.paper_mode,
            "kill_switch": self._kill_switch,
            "open_positions": {
                sym: {"side": pos.side, "entry_price": pos.entry_price, "quantity": pos.quantity}
                for sym, pos in self.positions.items()
            },
            "trade_count": len(self.trade_history),
            "total_pnl": sum(t.pnl for t in self.trade_history),
        }
