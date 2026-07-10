"use client";

import { cn } from "@/lib/utils";

interface SpaceGlyphProps {
  emoji: string | null | undefined;
  size?: number;
  className?: string;
}

export function SpaceGlyph({ emoji, size = 18, className }: SpaceGlyphProps) {
  return (
    <span
      className={cn("flex items-center justify-center shrink-0", className)}
      style={{ width: size, height: size, fontSize: size * 0.8 }}
      aria-hidden
    >
      {emoji || "📁"}
    </span>
  );
}
