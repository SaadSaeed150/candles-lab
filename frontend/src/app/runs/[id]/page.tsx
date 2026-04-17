"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import MetricsCard from "@/components/MetricsCard";
import EquityCurve from "@/components/EquityCurve";
import TradeTable from "@/components/TradeTable";
import LoadingSpinner from "@/components/LoadingSpinner";
import type { StrategyRun, EquityPoint, Trade, Signal } from "@/types";
import { ArrowLeft, Clock, DollarSign, BarChart3 } from "lucide-react";
import Link from "next/link";
import { clsx } from "clsx";

export default function RunDetailPage() {
  const params = useParams();
  const runId = Number(params.id);

  const [run, setRun] = useState<StrategyRun | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId) return;

    Promise.all([
      api.runDetail(runId),
      api.runEquity(runId),
      api.runSignals(runId),
      api.trades({ run: String(runId) }),
    ])
      .then(([runData, eqData, sigData, tradeData]) => {
        setRun(runData as unknown as StrategyRun);

        setEquity(
          (eqData as unknown as EquityPoint[]).map((p) => ({
            timestamp: p.timestamp,
            balance: Number(p.balance),
            unrealised_pnl: Number(p.unrealised_pnl),
            total_equity: Number(p.total_equity),
            drawdown: Number(p.drawdown),
          }))
        );

        setSignals(
          (sigData as unknown as Signal[]).map((s) => ({
            ...s,
            price: Number(s.price),
            confidence: Number(s.confidence),
          }))
        );

        setTrades(
          (tradeData as unknown as Trade[]).map((t, i) => ({
            id: i,
            symbol: t.symbol,
            side: t.side,
            entry_price: Number(t.entry_price),
            exit_price: Number(t.exit_price),
            quantity: Number(t.quantity),
            pnl: Number(t.pnl),
            net_pnl: Number((t as unknown as Record<string, unknown>).net_pnl ?? t.pnl),
            commission: Number((t as unknown as Record<string, unknown>).commission ?? 0),
            opened_at: t.opened_at,
            closed_at: t.closed_at,
          }))
        );
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return <LoadingSpinner size="lg" className="py-20" />;

  if (!run) {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-12 text-center text-sm text-[var(--color-text-muted)]">
        Run not found.
      </div>
    );
  }

  const metrics = run.metrics as Record<string, number> | null;
  const initialBal = Number(run.initial_balance);
  const finalBal = run.final_balance ? Number(run.final_balance) : initialBal;
  const pnl = finalBal - initialBal;
  const pnlPct = initialBal > 0 ? (pnl / initialBal) * 100 : 0;

  const signalCounts = signals.reduce<Record<string, number>>((acc, s) => {
    acc[s.action] = (acc[s.action] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          href="/runs"
          className="rounded-lg border border-[var(--color-border)] p-2 hover:bg-[var(--color-bg-hover)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold">
            {run.strategy_name}
            <span className="ml-2 text-base font-normal text-[var(--color-text-muted)]">
              #{run.id}
            </span>
          </h1>
          <div className="mt-1 flex gap-3 text-sm text-[var(--color-text-secondary)]">
            <span className="flex items-center gap-1">
              <BarChart3 className="h-3.5 w-3.5" />
              {run.mode}
            </span>
            <span>{run.symbol}</span>
            <span>{run.exchange} / {run.timeframe}</span>
            <span className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              {new Date(run.created_at).toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <MetricsCard
          label="Initial Balance"
          value={initialBal}
          prefix="$"
          trend="neutral"
        />
        <MetricsCard
          label="Final Equity"
          value={finalBal}
          prefix="$"
          trend={pnl >= 0 ? "up" : "down"}
          subtext={`${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%`}
        />
        <MetricsCard
          label="Return"
          value={pnl}
          prefix={pnl >= 0 ? "+$" : "$"}
          trend={pnl >= 0 ? "up" : "down"}
        />
        {metrics && metrics.win_rate !== undefined ? (
          <>
            <MetricsCard
              label="Win Rate"
              value={metrics.win_rate}
              suffix="%"
              trend={metrics.win_rate >= 50 ? "up" : "down"}
              subtext={`${metrics.win_count ?? 0}W / ${metrics.loss_count ?? 0}L`}
            />
            <MetricsCard
              label="Sharpe Ratio"
              value={metrics.sharpe_ratio ?? 0}
              trend={(metrics.sharpe_ratio ?? 0) > 0 ? "up" : "down"}
            />
          </>
        ) : (
          <>
            <MetricsCard label="Trades" value={trades.length} trend="neutral" />
            <MetricsCard label="Signals" value={signals.length} trend="neutral" />
          </>
        )}
      </div>

      {/* Performance Grid */}
      {metrics && metrics.total_trades !== undefined && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <MetricsCard label="Total Trades" value={metrics.total_trades} trend="neutral" />
          <MetricsCard label="Max Drawdown" value={((metrics.max_drawdown_pct ?? 0) * 100).toFixed(2)} suffix="%" trend="down" />
          <MetricsCard label="Profit Factor" value={metrics.profit_factor === Infinity ? "∞" : (metrics.profit_factor ?? 0)} trend={(metrics.profit_factor ?? 0) > 1 ? "up" : "down"} />
          <MetricsCard label="Expectancy" value={metrics.expectancy ?? 0} prefix="$" trend={(metrics.expectancy ?? 0) > 0 ? "up" : "down"} />
          <MetricsCard label="Sortino" value={metrics.sortino_ratio ?? 0} trend={(metrics.sortino_ratio ?? 0) > 0 ? "up" : "down"} />
        </div>
      )}

      {/* Equity Curve */}
      {equity.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">Equity Curve</h2>
          <EquityCurve data={equity} height={350} initialBalance={Number(run.initial_balance)} />
        </div>
      )}

      {/* Signal Distribution */}
      {signals.length > 0 && (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Signal Distribution ({signals.length} total)
          </h3>
          <div className="flex flex-wrap gap-4">
            {Object.entries(signalCounts).map(([action, count]) => (
              <div key={action} className="rounded-lg bg-[var(--color-bg-secondary)] px-4 py-3">
                <p className="text-xs text-[var(--color-text-muted)]">{action}</p>
                <p
                  className={clsx(
                    "text-xl font-bold tabular-nums",
                    action === "BUY" && "text-[var(--color-green)]",
                    action === "SELL" && "text-[var(--color-red)]",
                    action === "SHORT" && "text-[var(--color-red)]",
                    action === "COVER" && "text-[var(--color-green)]"
                  )}
                >
                  {count}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trades */}
      {trades.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">
            Trades
            <span className="ml-2 text-sm font-normal text-[var(--color-text-muted)]">
              ({trades.length})
            </span>
          </h2>
          <TradeTable trades={trades} />
        </div>
      )}
    </div>
  );
}
