"""
Moving Average Crossover strategy.

Uses a fast MA and slow MA. When the fast crosses above the slow,
it signals a BUY. When it crosses below, it signals a SELL.
Uses the price history available in the context to compute averages.
"""

from __future__ import annotations

from typing import Any

from trading_system.core.context import TradingContext
from trading_system.core import registry
from trading_system.strategies.base import BaseStrategy


class MACrossoverStrategy(BaseStrategy):
    """Simple dual moving average crossover."""

    FAST_PERIOD = 5
    SLOW_PERIOD = 15

    def _sma(self, prices: list[float], period: int) -> float | None:
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def on_data(self, data: dict[str, Any], context: TradingContext) -> dict[str, Any]:
        closes = [h["close"] for h in context.history if "close" in h]
        closes.append(data.get("close", 0.0))

        fast_ma = self._sma(closes, self.FAST_PERIOD)
        slow_ma = self._sma(closes, self.SLOW_PERIOD)

        if fast_ma is None or slow_ma is None:
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "meta": {"reason": "not enough data", "bars": len(closes)},
            }

        prev_closes = closes[:-1]
        prev_fast = self._sma(prev_closes, self.FAST_PERIOD)
        prev_slow = self._sma(prev_closes, self.SLOW_PERIOD)

        if prev_fast is None or prev_slow is None:
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "meta": {"reason": "not enough data for crossover"},
            }

        crossed_above = prev_fast <= prev_slow and fast_ma > slow_ma
        crossed_below = prev_fast >= prev_slow and fast_ma < slow_ma

        spread = abs(fast_ma - slow_ma) / slow_ma
        confidence = min(0.5 + spread * 10, 0.95)

        if crossed_above:
            return {
                "action": "BUY",
                "confidence": confidence,
                "meta": {
                    "reason": "fast MA crossed above slow MA",
                    "fast_ma": round(fast_ma, 4),
                    "slow_ma": round(slow_ma, 4),
                },
            }

        if crossed_below:
            return {
                "action": "SELL",
                "confidence": confidence,
                "meta": {
                    "reason": "fast MA crossed below slow MA",
                    "fast_ma": round(fast_ma, 4),
                    "slow_ma": round(slow_ma, 4),
                },
            }

        return {
            "action": "HOLD",
            "confidence": 0.3,
            "meta": {
                "reason": "no crossover",
                "fast_ma": round(fast_ma, 4),
                "slow_ma": round(slow_ma, 4),
                "trend": "bullish" if fast_ma > slow_ma else "bearish",
            },
        }


registry.register("ma_crossover", MACrossoverStrategy)
