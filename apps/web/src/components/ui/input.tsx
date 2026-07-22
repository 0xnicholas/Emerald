import { cn } from "@/lib/utils";
import { forwardRef, type InputHTMLAttributes } from "react";

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(({ className, type, ...props }, ref) => (
  <input
    ref={ref}
    type={type}
    className={cn(
      "flex h-9 w-full min-w-0 rounded-lg border border-surface-border bg-surface-card/30 bg-transparent px-3 py-1 text-sm text-fg-primary shadow-xs transition-[color,box-shadow] file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-fg-faint selection:bg-brand-accent/30 selection:text-fg-primary focus-visible:border-surface-ring focus-visible:ring-surface-ring/50 focus-visible:ring-2 focus-visible:outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
      className
    )}
    {...props}
  />
));
Input.displayName = "Input";
