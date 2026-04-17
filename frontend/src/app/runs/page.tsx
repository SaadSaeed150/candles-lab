"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import LoadingSpinner from "@/components/LoadingSpinner";
import { clsx } from "clsx";
import { ChevronRight, RefreshCw } from "lucide-react";
import type { StrategyRun } from "@/types";

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-[var(--color-green-dim)] text-[var(--color-green)]",
  running: "bg-[var(--color-accent)]/20 text-[var(--color-accent)]",
  failed: "bg-[var(--color-red-dim)] text-[var(--color-red)]",
  pending: "bg-[var(--color-bg-hover)] text-[var(--color-text-muted)]",
};

const MODE_COLORS: Record<string, string> = {
  backtest: "text-[var(--color-purple)]",
  paper: "text-[var(--color-accent)]",
  live: "text-[var(--color-amber)]",
};

export default function RunsPage() {
  const [runs, setRuns] = useState<StrategyRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("");

  async function fetchRuns() {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (filter) params["mode"] = filter;
      const data = (await api.runs(params)) as unknown as StrategyRun[];
      setRuns(data);
    } catch {
      // silently handle
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchRuns();
  }, [filter]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Strategy Runs</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            View and analyze all past strategy executions
          </p>
        </div>
        <button
          onClick={fetchRuns}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {["", "backtest", "paper", "live"].map((mode) => (
          <button
            key={mode}
            onClick={() => setFilter(mode)}
            className={clsx(
              "rounded-lg px-3 py-1.5 text-xs font-medium transition",
              filter === mode
                ? "bg-[var(--color-accent)] text-white"
                : "bg-[var(--color-bg-card)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]"
            )}
          >
            {mode || "All"}
          </button>
        ))}
      </div>

      {loading && <LoadingSpinner size="lg" className="py-20" />}

      {!loading && runs.length === 0 && (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-12 text-center text-sm text-[var(--color-text-muted)]">
          No strategy runs found. Run a simulation or backtest to see results here.
        </div>
      )}

      {!loading && runs.length > 0 && (
        <div className="space-y-2">
          {runs.map((run) => {
            const pnl = run.final_balance
              ? Number(run.final_balance) - Number(run.initial_balance)
              : null;

            return (
              <Link
                key={run.id}
                href={`/runs/${run.id}`}
                className="flex items-center justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 transition hover:border-[var(--color-accent)]/30 hover:bg-[var(--color-bg-hover)]"
              >
                <div className="flex items-center gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{run.strategy_name}</span>
                      <span className={clsx("text-xs font-medium", MODE_COLORS[run.mode] ?? "")}>
                        {run.mode}
                      </span>
                      <span
                        className={clsx(
                          "rounded px-2 py-0.5 text-xs font-medium",
                          STATUS_COLORS[run.status] ?? STATUS_COLORS.pending
                        )}
                      >
                        {run.status}
                      </span>
                    </div>
                    <div className="mt-1 flex gap-3 text-xs text-[var(--color-text-muted)]">
                      <span>{run.symbol}</span>
                      <span>{run.exchange}</span>
                      <span>{run.timeframe}</span>
                      <span>{new Date(run.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-4">
                  {pnl !== null && (
                    <span
                      className={clsx(
                        "text-sm font-bold tabular-nums",
                        pnl >= 0 ? "text-[var(--color-green)]" : "text-[var(--color-red)]"
                      )}
                    >
                      {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                    </span>
                  )}
                  <ChevronRight className="h-4 w-4 text-[var(--color-text-muted)]" />
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
