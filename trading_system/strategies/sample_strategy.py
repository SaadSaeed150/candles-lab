"""
Sample strategy — a trivial threshold-based example.

Rules:
    close < 100  →  BUY
    close > 110  →  SELL
    otherwise    →  HOLD

This exists purely to demonstrate the plug-and-play interface;
replace it with real logic for production use.
"""

from __future__ import annotations

from typing import Any

from trading_system.core.context import TradingContext
from trading_system.core import registry
from trading_system.strategies.base import BaseStrategy


class SampleStrategy(BaseStrategy):
    """Threshold strategy: buy low, sell high, hold in between."""

    BUY_THRESHOLD = 100.0
    SELL_THRESHOLD = 110.0

    def on_data(self, data: dict[str, Any], context: TradingContext) -> dict[str, Any]:
        close = data.get("close", 0.0)

        if close < self.BUY_THRESHOLD:
            return {
                "action": "BUY",
                "confidence": 0.7,
                "meta": {"reason": f"close {close} < {self.BUY_THRESHOLD}"},
            }

        if close > self.SELL_THRESHOLD:
            return {
                "action": "SELL",
                "confidence": 0.8,
                "meta": {"reason": f"close {close} > {self.SELL_THRESHOLD}"},
            }

        return {
            "action": "HOLD",
            "confidence": 0.5,
            "meta": {"reason": "within range"},
        }


registry.register("sample", SampleStrategy)
