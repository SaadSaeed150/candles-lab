"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import MetricsCard from "@/components/MetricsCard";
import Chart from "@/components/Chart";
import TradeTable from "@/components/TradeTable";
import LoadingSpinner from "@/components/LoadingSpinner";
import type { Candle, Trade } from "@/types";
import { Activity, Zap } from "lucide-react";

interface SimResult {
  run_id: number;
  ticks_processed: number;
  final_balance: number;
  trades_completed: number;
  total_pnl: number;
  results: Array<{
    data: Candle;
    action: string;
    executed: string;
    pnl?: number;
  }>;
}

export default function DashboardPage() {
  const [strategies, setStrategies] = useState<string[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState("sample");
  const [numPoints, setNumPoints] = useState(200);
  const [balance, setBalance] = useState(10000);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SimResult | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.strategies().then((d) => {
      setStrategies(d.strategies);
      if (d.strategies.length > 0 && !d.strategies.includes(selectedStrategy)) {
        setSelectedStrategy(d.strategies[0]);
      }
    }).catch(() => {});
  }, [selectedStrategy]);

  const runSimulation = useCallback(async () => {
    setRunning(true);
    setError("");
    try {
      const data = (await api.simulate({
        strategy: selectedStrategy,
        num_points: numPoints,
        initial_balance: balance,
      })) as unknown as SimResult;

      setResult(data);

      const chartCandles = data.results.map((r) => r.data);
      setCandles(chartCandles);

      const tradeList: Trade[] = [];
      let tradeIdx = 0;
      for (const r of data.results) {
        if (r.executed === "SELL" || r.executed === "COVER") {
          tradeList.push({
            id: tradeIdx++,
            symbol: r.data.symbol ?? "BTCUSDT",
            side: r.executed === "SELL" ? "LONG" : "SHORT",
            entry_price: 0,
            exit_price: r.data.close,
            quantity: 0,
            pnl: r.pnl ?? 0,
            opened_at: r.data.time,
            closed_at: r.data.time,
          });
        }
      }
      setTrades(tradeList);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Simulation failed");
    } finally {
      setRunning(false);
    }
  }, [selectedStrategy, numPoints, balance]);

  type Marker = {
    time: string;
    position: "aboveBar" | "belowBar";
    color: string;
    shape: "arrowUp" | "arrowDown" | "circle";
    text: string;
  };

  const markers: Marker[] = result
    ? [
        ...result.results
          .filter((r) => r.executed === "BUY" || r.executed === "SHORT")
          .map((r): Marker => ({
            time: r.data.time,
            position: "belowBar",
            color: r.executed === "BUY" ? "#22c55e" : "#ef4444",
            shape: r.executed === "BUY" ? "arrowUp" : "arrowDown",
            text: r.executed,
          })),
        ...result.results
          .filter((r) => r.executed === "SELL" || r.executed === "COVER")
          .map((r): Marker => ({
            time: r.data.time,
            position: "aboveBar",
            color: r.executed === "SELL" ? "#ef4444" : "#22c55e",
            shape: r.executed === "SELL" ? "arrowDown" : "arrowUp",
            text: r.executed,
          })),
      ]
    : [];

  const pnl = result?.total_pnl ?? 0;
  const pnlPct = result ? ((result.final_balance - balance) / balance) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            Run simulations and analyze trading strategies
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-[var(--color-green)]" />
          <span className="text-xs text-[var(--color-text-muted)]">System Online</span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
            Strategy
          </label>
          <select
            value={selectedStrategy}
            onChange={(e) => setSelectedStrategy(e.target.value)}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
          >
            {strategies.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
            Data Points
          </label>
          <input
            type="number"
            value={numPoints}
            onChange={(e) => setNumPoints(Number(e.target.value))}
            min={10}
            max={5000}
            className="w-28 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
            Initial Balance
          </label>
          <input
            type="number"
            value={balance}
            onChange={(e) => setBalance(Number(e.target.value))}
            min={100}
            className="w-32 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
          />
        </div>

        <button
          onClick={runSimulation}
          disabled={running}
          className="flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition hover:bg-[var(--color-accent-hover)] disabled:opacity-50"
        >
          <Zap className="h-4 w-4" />
          {running ? "Running..." : "Run Simulation"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-[var(--color-red-dim)] px-4 py-3 text-sm text-[var(--color-red)]">
          {error}
        </div>
      )}

      {running && <LoadingSpinner size="lg" className="py-20" />}

      {/* Results */}
      {result && !running && (
        <>
          {/* Metrics */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <MetricsCard
              label="Final Balance"
              value={result.final_balance}
              prefix="$"
              trend={result.final_balance >= balance ? "up" : "down"}
            />
            <MetricsCard
              label="Total PnL"
              value={pnl}
              prefix="$"
              trend={pnl >= 0 ? "up" : "down"}
              subtext={`${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%`}
            />
            <MetricsCard
              label="Trades"
              value={result.trades_completed}
              trend="neutral"
            />
            <MetricsCard
              label="Ticks Processed"
              value={result.ticks_processed}
              trend="neutral"
            />
          </div>

          {/* Chart */}
          <div>
            <h2 className="mb-3 text-lg font-semibold">Price Chart</h2>
            <Chart candles={candles} markers={markers} height={450} />
          </div>

          {/* Trades */}
          {trades.length > 0 && (
            <div>
              <h2 className="mb-3 text-lg font-semibold">
                Trade History
                <span className="ml-2 text-sm font-normal text-[var(--color-text-muted)]">
                  ({trades.length} trades)
                </span>
              </h2>
              <TradeTable trades={trades} maxRows={20} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
