import { cn } from "@/lib/utils";
import { forwardRef, type ButtonHTMLAttributes } from "react";

const buttonVariants = {
  default:
    "bg-gradient-to-b from-[#1C2026] to-[#12161C] text-white shadow-[inset_-2px_-2px_6px_0_rgba(0,0,0,0.15),inset_2px_2px_4px_0_rgba(255,255,255,0.05)] hover:from-[#1C2026]/90 hover:to-[#12161C]/90",
  primary:
    "bg-brand-accent text-white shadow-xs hover:brightness-110",
  outline:
    "border border-surface-border bg-surface-card shadow-xs hover:bg-surface-hover",
  secondary:
    "bg-surface-hover text-fg-primary hover:bg-surface-border",
  ghost: "hover:bg-surface-hover text-fg-muted hover:text-fg-primary",
  danger: "bg-red-600 text-white hover:bg-red-700 shadow-xs",
};

const buttonSizes = {
  sm: "h-8 px-3 text-xs rounded-lg",
  md: "h-10 px-4 text-sm rounded-xl",
  lg: "h-12 px-6 text-base rounded-xl",
  icon: "h-10 w-10 rounded-xl",
  "icon-sm": "h-8 w-8 rounded-lg",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof buttonVariants;
  size?: keyof typeof buttonSizes;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-surface-ring/60 disabled:pointer-events-none disabled:opacity-50 cursor-pointer select-none",
        buttonVariants[variant],
        buttonSizes[size],
        className
      )}
      {...props}
    />
  )
);
Button.displayName = "Button";
