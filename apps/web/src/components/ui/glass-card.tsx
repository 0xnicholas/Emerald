import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

interface GlassCardProps extends HTMLAttributes<HTMLDivElement> {
  /** Background opacity. Default: 60 */
  bgOpacity?: number;
  /** Blur intensity. Default: md */
  blur?: "sm" | "md" | "lg" | "xl";
  /** Shadow intensity. Default: md */
  shadow?: "sm" | "md" | "lg" | "xl";
  /** Hover effect: elevate shadow on hover */
  hoverable?: boolean;
}

const blurMap = {
  sm: "backdrop-blur-sm",
  md: "backdrop-blur-md",
  lg: "backdrop-blur-lg",
  xl: "backdrop-blur-xl",
} as const;

const shadowMap = {
  sm: "shadow-sm",
  md: "shadow-[0_12px_40px_rgba(0,0,0,0.22)]",
  lg: "shadow-[0_12px_40px_rgba(0,0,0,0.34)]",
  xl: "shadow-[0_20px_60px_rgba(0,0,0,0.5)]",
} as const;

export function GlassCard({
  className,
  bgOpacity = 60,
  blur = "md",
  shadow = "md",
  hoverable = false,
  style,
  ...props
}: GlassCardProps) {
  return (
    <div
      className={cn(
        "rounded-[18px] border border-surface-border backdrop-blur-md transition-all",
        blurMap[blur],
        shadowMap[shadow],
        hoverable && "hover:shadow-[0_12px_40px_rgba(0,0,0,0.34)]",
        className
      )}
      style={{ backgroundColor: `rgb(16 24 34 / ${bgOpacity}%)`, ...style }}
      {...props}
    />
  );
}
