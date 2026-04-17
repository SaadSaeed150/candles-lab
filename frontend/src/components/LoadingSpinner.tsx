"use client";

import { clsx } from "clsx";

export default function LoadingSpinner({
  size = "md",
  className,
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const sizeClasses = { sm: "h-4 w-4", md: "h-6 w-6", lg: "h-10 w-10" };

  return (
    <div className={clsx("flex items-center justify-center", className)}>
      <div
        className={clsx(
          "animate-spin rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-accent)]",
          sizeClasses[size]
        )}
      />
    </div>
  );
}
