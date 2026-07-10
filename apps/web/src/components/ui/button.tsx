import { cn } from "@/lib/utils";
import { forwardRef, type ButtonHTMLAttributes } from "react";

const variants = {
  default:
    "bg-brand-accent text-white hover:brightness-110 shadow-xs",
  secondary:
    "bg-surface-hover text-fg-primary hover:bg-surface-border",
  outline:
    "border border-surface-border hover:bg-surface-hover",
  ghost: "hover:bg-surface-hover",
  danger: "bg-red-600 text-white hover:bg-red-700",
};

const sizes = {
  sm: "h-8 px-3 text-xs",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
  icon: "h-10 w-10",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-surface-ring focus:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    />
  )
);
Button.displayName = "Button";
