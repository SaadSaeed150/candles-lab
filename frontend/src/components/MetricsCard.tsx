"use client";

import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { clsx } from "clsx";

interface MetricsCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  trend?: "up" | "down" | "neutral";
  prefix?: string;
  suffix?: string;
}

export default function MetricsCard({
  label,
  value,
  subtext,
  trend,
  prefix = "",
  suffix = "",
}: MetricsCardProps) {
  const TrendIcon =
    trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
        {label}
      </p>
      <div className="mt-2 flex items-end gap-2">
        <span
          className={clsx(
            "text-2xl font-bold tabular-nums",
            trend === "up" && "text-[var(--color-green)]",
            trend === "down" && "text-[var(--color-red)]"
          )}
        >
          {prefix}
          {typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value}
          {suffix}
        </span>
        {trend && (
          <TrendIcon
            className={clsx(
              "mb-1 h-4 w-4",
              trend === "up" && "text-[var(--color-green)]",
              trend === "down" && "text-[var(--color-red)]",
              trend === "neutral" && "text-[var(--color-text-muted)]"
            )}
          />
        )}
      </div>
      {subtext && (
        <p className="mt-1 text-xs text-[var(--color-text-muted)]">{subtext}</p>
      )}
    </div>
  );
}
