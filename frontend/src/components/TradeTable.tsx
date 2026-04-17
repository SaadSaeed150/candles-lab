"use client";

import { clsx } from "clsx";
import type { Trade } from "@/types";

interface TradeTableProps {
  trades: Trade[];
  maxRows?: number;
}

export default function TradeTable({ trades, maxRows }: TradeTableProps) {
  const visible = maxRows ? trades.slice(0, maxRows) : trades;

  if (visible.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8 text-center text-sm text-[var(--color-text-muted)]">
        No trades to display.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-xs uppercase tracking-wider text-[var(--color-text-muted)]">
            <th className="px-4 py-3">#</th>
            <th className="px-4 py-3">Symbol</th>
            <th className="px-4 py-3">Side</th>
            <th className="px-4 py-3 text-right">Entry</th>
            <th className="px-4 py-3 text-right">Exit</th>
            <th className="px-4 py-3 text-right">Qty</th>
            <th className="px-4 py-3 text-right">PnL</th>
            <th className="px-4 py-3 text-right">Commission</th>
            <th className="px-4 py-3">Opened</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((trade, i) => (
            <tr
              key={trade.id ?? i}
              className="border-b border-[var(--color-border)]/50 transition-colors hover:bg-[var(--color-bg-hover)]"
            >
              <td className="px-4 py-2.5 text-[var(--color-text-muted)]">
                {i + 1}
              </td>
              <td className="px-4 py-2.5 font-medium">{trade.symbol}</td>
              <td className="px-4 py-2.5">
                <span
                  className={clsx(
                    "inline-block rounded px-2 py-0.5 text-xs font-semibold",
                    trade.side === "LONG"
                      ? "bg-[var(--color-green-dim)] text-[var(--color-green)]"
                      : "bg-[var(--color-red-dim)] text-[var(--color-red)]"
                  )}
                >
                  {trade.side}
                </span>
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums">
                {Number(trade.entry_price).toFixed(2)}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums">
                {Number(trade.exit_price).toFixed(2)}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums">
                {Number(trade.quantity).toFixed(4)}
              </td>
              <td
                className={clsx(
                  "px-4 py-2.5 text-right font-medium tabular-nums",
                  Number(trade.pnl) >= 0
                    ? "text-[var(--color-green)]"
                    : "text-[var(--color-red)]"
                )}
              >
                {Number(trade.pnl) >= 0 ? "+" : ""}
                {Number(trade.pnl).toFixed(2)}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums text-[var(--color-text-muted)]">
                {trade.commission != null ? Number(trade.commission).toFixed(2) : "—"}
              </td>
              <td className="px-4 py-2.5 text-[var(--color-text-muted)]">
                {new Date(trade.opened_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {maxRows && trades.length > maxRows && (
        <div className="border-t border-[var(--color-border)] px-4 py-2 text-center text-xs text-[var(--color-text-muted)]">
          Showing {maxRows} of {trades.length} trades
        </div>
      )}
    </div>
  );
}
