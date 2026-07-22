import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

const badgeVariants = {
  default: "border-transparent bg-primary/10 text-fg-primary",
  secondary: "border-transparent bg-surface-hover text-fg-muted",
  accent: "border-transparent bg-brand-accent-subtle text-brand-accent",
  success: "border-transparent bg-bg-success text-text-success",
  warning: "border-transparent bg-bg-warning text-text-warning",
  error: "border-transparent bg-bg-error text-text-error",
  outline: "border-surface-border text-fg-muted",
} as const;

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: keyof typeof badgeVariants;
}

export function Badge({
  className,
  variant = "default",
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-full px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 gap-1 border border-surface-border/30 transition-[color,box-shadow]",
        badgeVariants[variant],
        className
      )}
      {...props}
    />
  );
}
