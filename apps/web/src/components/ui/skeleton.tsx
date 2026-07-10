import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Number of skeleton lines (default: 1) */
  lines?: number;
  /** Last line width (default: "60%") */
  lastLineWidth?: string;
}

export function Skeleton({
  className,
  lines = 1,
  lastLineWidth = "60%",
  ...props
}: SkeletonProps) {
  if (lines === 1) {
    return (
      <div
        className={cn(
          "animate-pulse-soft rounded-md bg-surface-skeleton",
          className
        )}
        {...props}
      />
    );
  }

  return (
    <div className="space-y-2" {...props}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "animate-pulse-soft rounded-md bg-surface-skeleton",
            i === lines - 1 ? lastLineWidth : "w-full",
            className
          )}
          style={{ height: className ? undefined : 14 }}
        />
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <Skeleton className="h-5 w-5 rounded-md" />
        <Skeleton className="h-4 w-16 rounded-full" />
        <Skeleton className="ml-auto h-4 w-10 rounded-md" />
      </div>
      <Skeleton lines={2} className="h-3" lastLineWidth="80%" />
      <div className="mt-3 flex items-center gap-2 border-t border-surface-border pt-3">
        <Skeleton className="h-4 w-14 rounded-md" />
        <Skeleton className="h-4 w-24 rounded-md" />
      </div>
    </div>
  );
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-card p-5">
      <Skeleton className="mb-4 h-11 w-11 rounded-xl" />
      <Skeleton className="mb-1 h-7 w-20" />
      <Skeleton className="h-4 w-32" />
    </div>
  );
}
