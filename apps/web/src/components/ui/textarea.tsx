import { cn } from "@/lib/utils";
import { forwardRef, type TextareaHTMLAttributes } from "react";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex min-h-16 w-full rounded-lg border border-surface-border bg-surface-card/30 bg-transparent px-3 py-2 text-sm text-fg-primary shadow-xs transition-[color,box-shadow] placeholder:text-fg-faint selection:bg-brand-accent/30 selection:text-fg-primary focus-visible:border-surface-ring focus-visible:ring-surface-ring/50 focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm resize-none field-sizing-content",
      className
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
