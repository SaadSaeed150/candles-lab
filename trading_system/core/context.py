"""
Trading context — carries runtime state passed to strategies on every tick.

The context is a read-only snapshot that strategies use to make decisions
without directly touching the trader's internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TradingContext:
    """Immutable snapshot of the current trading state.

    Attributes:
        balance:          Available cash.
        equity:           Total equity (balance + unrealised PnL).
        position:         Current position direction — "LONG", "SHORT", or None.
        entry_price:      Price at which the current position was opened (None if flat).
        open_positions:   Number of currently open positions.
        drawdown:         Current drawdown from peak equity (0.0 - 1.0).
        total_pnl:        Cumulative realised PnL.
        trade_count:      Number of completed trades so far.
        history:          Past data points the engine has processed so far.
        extra:            Arbitrary key-value pairs strategies may need.
    """

    balance: float = 10_000.0
    equity: float = 10_000.0
    position: str | None = None
    entry_price: float | None = None
    open_positions: int = 0
    drawdown: float = 0.0
    total_pnl: float = 0.0
    trade_count: int = 0
    history: tuple[dict[str, Any], ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "equity": self.equity,
            "position": self.position,
            "entry_price": self.entry_price,
            "open_positions": self.open_positions,
            "drawdown": self.drawdown,
            "total_pnl": self.total_pnl,
            "trade_count": self.trade_count,
            "history_length": len(self.history),
            "extra": self.extra,
        }
