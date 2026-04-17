"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import Chart from "@/components/Chart";
import LoadingSpinner from "@/components/LoadingSpinner";
import type { Candle } from "@/types";
import { Search } from "lucide-react";

export default function MarketPage() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [timeframe, setTimeframe] = useState("1m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.marketData({ symbol, timeframe });
      const mapped: Candle[] = (data as unknown as Array<{
        time: string;
        open: string;
        high: string;
        low: string;
        close: string;
        volume: string;
      }>).map((d) => ({
        time: d.time,
        open: Number(d.open),
        high: Number(d.high),
        low: Number(d.low),
        close: Number(d.close),
        volume: Number(d.volume),
      }));
      setCandles(mapped);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Market Data</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">
          Browse stored OHLCV market data
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
            Symbol
          </label>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="w-36 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
            Timeframe
          </label>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
          >
            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
        </div>

        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition hover:bg-[var(--color-accent-hover)] disabled:opacity-50"
        >
          <Search className="h-4 w-4" />
          Load
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-[var(--color-red-dim)] px-4 py-3 text-sm text-[var(--color-red)]">
          {error}
        </div>
      )}

      {loading && <LoadingSpinner size="lg" className="py-20" />}

      {!loading && candles.length > 0 && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold">{symbol} — {timeframe}</h2>
            <span className="text-xs text-[var(--color-text-muted)]">
              {candles.length} candles
            </span>
          </div>
          <Chart candles={candles} height={500} />
        </div>
      )}

      {!loading && candles.length === 0 && !error && (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-12 text-center text-sm text-[var(--color-text-muted)]">
          No market data found for {symbol} ({timeframe}). Use the data ingestion API to backfill data first.
        </div>
      )}
    </div>
  );
}
