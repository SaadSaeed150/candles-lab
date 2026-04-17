"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
  ColorType,
} from "lightweight-charts";
import type { Candle } from "@/types";

interface ChartProps {
  candles: Candle[];
  height?: number;
  showVolume?: boolean;
  markers?: Array<{
    time: string;
    position: "aboveBar" | "belowBar";
    color: string;
    shape: "arrowUp" | "arrowDown" | "circle";
    text: string;
  }>;
}

function toChartTime(iso: string): Time {
  return Math.floor(new Date(iso).getTime() / 1000) as Time;
}

export default function Chart({
  candles,
  height = 400,
  showVolume = true,
  markers,
}: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

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
        vertLines: { color: "#2a355330" },
        horzLines: { color: "#2a355330" },
      },
      crosshair: {
        vertLine: { color: "#3b82f6", width: 1, style: 2 },
        horzLine: { color: "#3b82f6", width: 1, style: 2 },
      },
      timeScale: {
        borderColor: "#2a3553",
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: "#2a3553",
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e80",
      wickDownColor: "#ef444480",
    });

    candleSeriesRef.current = candleSeries;

    if (showVolume) {
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeriesRef.current = volumeSeries;
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
      chartRef.current = null;
    };
  }, [height, showVolume]);

  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    const data: CandlestickData[] = candles.map((c) => ({
      time: toChartTime(c.time),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    candleSeriesRef.current.setData(data);

    if (showVolume && volumeSeriesRef.current) {
      volumeSeriesRef.current.setData(
        candles.map((c) => ({
          time: toChartTime(c.time),
          value: c.volume,
          color: c.close >= c.open ? "#22c55e30" : "#ef444430",
        }))
      );
    }

    if (markers && markers.length > 0) {
      const sorted = markers
        .map((m) => ({ ...m, time: toChartTime(m.time) }))
        .sort((a, b) => (a.time as number) - (b.time as number));
      candleSeriesRef.current.setMarkers(sorted);
    }

    chartRef.current?.timeScale().fitContent();
  }, [candles, markers, showVolume]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-xl border border-[var(--color-border)] overflow-hidden"
    />
  );
}
