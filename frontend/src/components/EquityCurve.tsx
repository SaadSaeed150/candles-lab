"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  type IChartApi,
  type Time,
  ColorType,
} from "lightweight-charts";
import type { EquityPoint } from "@/types";

interface EquityCurveProps {
  data: EquityPoint[];
  height?: number;
  initialBalance?: number;
}

export default function EquityCurve({
  data,
  height = 300,
  initialBalance = 10000,
}: EquityCurveProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#1a2035" },
        textColor: "#8892a8",
        fontFamily: "Inter, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: "#2a355320" },
        horzLines: { color: "#2a355320" },
      },
      rightPriceScale: { borderColor: "#2a3553" },
      timeScale: { borderColor: "#2a3553", timeVisible: true },
    });

    const equitySeries = chart.addAreaSeries({
      topColor: "#3b82f640",
      bottomColor: "#3b82f605",
      lineColor: "#3b82f6",
      lineWidth: 2,
    });

    const drawdownSeries = chart.addAreaSeries({
      topColor: "#ef444400",
      bottomColor: "#ef444420",
      lineColor: "#ef4444",
      lineWidth: 1,
      priceScaleId: "drawdown",
    });

    chart.priceScale("drawdown").applyOptions({
      scaleMargins: { top: 0, bottom: 0.7 },
    });

    if (data.length > 0) {
      equitySeries.setData(
        data.map((p) => ({
          time: (Math.floor(new Date(p.timestamp).getTime() / 1000)) as Time,
          value: Number(p.total_equity),
        }))
      );

      drawdownSeries.setData(
        data.map((p) => ({
          time: (Math.floor(new Date(p.timestamp).getTime() / 1000)) as Time,
          value: Number(p.drawdown) * 100,
        }))
      );

      chart.timeScale().fitContent();
    }

    chartRef.current = chart;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [data, height, initialBalance]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] text-sm text-[var(--color-text-muted)]"
        style={{ height }}
      >
        No equity data available.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-full rounded-xl border border-[var(--color-border)] overflow-hidden"
    />
  );
}
