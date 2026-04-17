"""
Abstract base for all trading strategies.

Every strategy *must* subclass `BaseStrategy` and implement `on_data`.
The engine relies on this interface — strategies that don't follow it
will be rejected at registration time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from trading_system.core.context import TradingContext


class BaseStrategy(ABC):
    """Contract that every trading strategy must fulfil.

    Subclasses receive market data and a read-only context snapshot,
    and must return a standardised decision dict.
    """

    @abstractmethod
    def on_data(self, data: dict[str, Any], context: TradingContext) -> dict[str, Any]:
        """Evaluate a single data point and return a trading decision.

        Required keys in the returned dict:
            action: "BUY" | "SELL" | "SHORT" | "COVER" | "HOLD"

        Optional keys:
            confidence:  float  — how sure the strategy is (0-1).
            stop_loss:   float  — suggested stop-loss price.
            take_profit: float  — suggested take-profit price.
            meta:        dict   — any extra info for logging/debugging.
        """
        ...
