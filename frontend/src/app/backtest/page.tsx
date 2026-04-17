"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import MetricsCard from "@/components/MetricsCard";
import Chart from "@/components/Chart";
import EquityCurve from "@/components/EquityCurve";
import TradeTable from "@/components/TradeTable";
import LoadingSpinner from "@/components/LoadingSpinner";
import type { BacktestReport, Trade, EquityPoint, Candle } from "@/types";
import { FlaskConical, Settings2 } from "lucide-react";

export default function BacktestPage() {
  const [strategies, setStrategies] = useState<string[]>([]);
  const [form, setForm] = useState({
    strategy: "sample",
    feed_source: "synthetic",
    synthetic_points: 500,
    synthetic_start_price: 100,
    initial_balance: 10000,
    commission_rate: 0.001,
    slippage_rate: 0.0005,
  });
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.strategies().then((d) => setStrategies(d.strategies)).catch(() => {});
  }, []);

  const runBacktest = useCallback(async () => {
    setLoading(true);
    setError("");
    setReport(null);
    try {
      const data = (await api.backtestSync(form)) as unknown as BacktestReport;
      setReport(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Backtest failed");
    } finally {
      setLoading(false);
    }
  }, [form]);

  function update(key: string, value: string | number) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const perf = report?.performance;
  const equityData: EquityPoint[] = (report?.equity_curve ?? []).map((p) => ({
    timestamp: p.timestamp ?? new Date().toISOString(),
    balance: Number(p.balance),
    unrealised_pnl: Number(p.unrealised_pnl),
    total_equity: Number(p.total_equity),
    drawdown: Number(p.drawdown),
  }));

  const trades: Trade[] = (report?.trades ?? []).map((t, i) => ({
    id: i,
    symbol: t.symbol,
    side: t.side,
    entry_price: Number(t.entry_price),
    exit_price: Number(t.exit_price),
    quantity: Number(t.quantity),
    pnl: Number(t.pnl),
    net_pnl: Number(t.net_pnl),
    commission: Number(t.commission),
    opened_at: t.opened_at,
    closed_at: t.closed_at,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Backtest</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">
          Test strategies on historical or synthetic data
        </p>
      </div>

      {/* Form */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
              Strategy
            </label>
            <select
              value={form.strategy}
              onChange={(e) => update("strategy", e.target.value)}
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
            >
              {strategies.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
              Data Points
            </label>
            <input
              type="number"
              value={form.synthetic_points}
              onChange={(e) => update("synthetic_points", Number(e.target.value))}
              min={10}
              max={10000}
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
              Initial Balance
            </label>
            <input
              type="number"
              value={form.initial_balance}
              onChange={(e) => update("initial_balance", Number(e.target.value))}
              min={100}
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
            />
          </div>
        </div>

        {/* Advanced */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="mt-4 flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
        >
          <Settings2 className="h-3.5 w-3.5" />
          {showAdvanced ? "Hide" : "Show"} advanced settings
        </button>

        {showAdvanced && (
          <div className="mt-3 grid grid-cols-1 gap-4 border-t border-[var(--color-border)] pt-4 md:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
                Start Price
              </label>
              <input
                type="number"
                value={form.synthetic_start_price}
                onChange={(e) => update("synthetic_start_price", Number(e.target.value))}
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
                Commission Rate
              </label>
              <input
                type="number"
                step="0.0001"
                value={form.commission_rate}
                onChange={(e) => update("commission_rate", Number(e.target.value))}
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
                Slippage Rate
              </label>
              <input
                type="number"
                step="0.0001"
                value={form.slippage_rate}
                onChange={(e) => update("slippage_rate", Number(e.target.value))}
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
              />
            </div>
          </div>
        )}

        <div className="mt-4">
          <button
            onClick={runBacktest}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-[var(--color-accent-hover)] disabled:opacity-50"
          >
            <FlaskConical className="h-4 w-4" />
            {loading ? "Running Backtest..." : "Run Backtest"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-[var(--color-red-dim)] px-4 py-3 text-sm text-[var(--color-red)]">
          {error}
        </div>
      )}

      {loading && <LoadingSpinner size="lg" className="py-20" />}

      {/* Results */}
      {report && perf && !loading && (
        <>
          {/* Headline Metrics */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <MetricsCard
              label="Net PnL"
              value={perf.total_net_pnl}
              prefix="$"
              trend={perf.total_net_pnl >= 0 ? "up" : "down"}
            />
            <MetricsCard
              label="Win Rate"
              value={perf.win_rate}
              suffix="%"
              trend={perf.win_rate >= 50 ? "up" : "down"}
              subtext={`${perf.win_count}W / ${perf.loss_count}L`}
            />
            <MetricsCard
              label="Sharpe Ratio"
              value={perf.sharpe_ratio}
              trend={perf.sharpe_ratio > 1 ? "up" : perf.sharpe_ratio < 0 ? "down" : "neutral"}
            />
            <MetricsCard
              label="Max Drawdown"
              value={(perf.max_drawdown_pct * 100).toFixed(2)}
              suffix="%"
              trend="down"
            />
            <MetricsCard
              label="Profit Factor"
              value={perf.profit_factor === Infinity ? "∞" : perf.profit_factor}
              trend={perf.profit_factor > 1 ? "up" : "down"}
            />
          </div>

          {/* Additional Metrics */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <MetricsCard label="Total Trades" value={perf.total_trades} trend="neutral" />
            <MetricsCard label="Avg Win" value={perf.avg_win} prefix="$" trend="up" />
            <MetricsCard label="Avg Loss" value={perf.avg_loss} prefix="$" trend="down" />
            <MetricsCard label="Expectancy" value={perf.expectancy} prefix="$" trend={perf.expectancy > 0 ? "up" : "down"} />
          </div>

          {/* Equity Curve */}
          <div>
            <h2 className="mb-3 text-lg font-semibold">Equity Curve</h2>
            <EquityCurve data={equityData} height={350} initialBalance={form.initial_balance} />
          </div>

          {/* Trades */}
          {trades.length > 0 && (
            <div>
              <h2 className="mb-3 text-lg font-semibold">
                Trades
                <span className="ml-2 text-sm font-normal text-[var(--color-text-muted)]">
                  ({trades.length})
                </span>
              </h2>
              <TradeTable trades={trades} maxRows={50} />
            </div>
          )}

          {/* Trade Distribution */}
          {report.trade_distribution && (
            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6">
              <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Trade Distribution
              </h3>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                {Object.entries(report.trade_distribution).map(([key, val]) => (
                  <div key={key}>
                    <p className="text-xs text-[var(--color-text-muted)]">{key.replace(/_/g, " ")}</p>
                    <p className="text-xl font-bold tabular-nums">{val}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
