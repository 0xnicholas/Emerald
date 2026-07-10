import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

type HeadingLevel = "h1" | "h2" | "h3" | "h4";
type Weight = "bold" | "medium";

interface HeadingProps extends HTMLAttributes<HTMLHeadingElement> {
  level?: HeadingLevel;
  weight?: Weight;
}

const headingStyles: Record<HeadingLevel, string> = {
  h1: "text-2xl md:text-3xl",
  h2: "text-xl md:text-2xl",
  h3: "text-lg md:text-xl",
  h4: "text-base md:text-lg",
};

const weightStyles: Record<Weight, string> = {
  bold: "font-bold",
  medium: "font-medium",
};

export function Heading({
  level = "h1",
  weight = "bold",
  className,
  ...props
}: HeadingProps) {
  const Tag = level;
  return (
    <Tag
      className={cn(
        "tracking-tight text-fg-primary",
        headingStyles[level],
        weightStyles[weight],
        className
      )}
      {...props}
    />
  );
}

type LabelLevel = "1" | "2" | "3";

interface LabelProps extends HTMLAttributes<HTMLSpanElement> {
  level?: LabelLevel;
  weight?: Weight;
}

const labelStyles: Record<LabelLevel, string> = {
  "1": "text-sm",
  "2": "text-xs",
  "3": "text-[10px] uppercase tracking-[0.12em]",
};

export function Label({
  level = "2",
  weight = "medium",
  className,
  ...props
}: LabelProps) {
  return (
    <span
      className={cn(
        "text-fg-muted",
        labelStyles[level],
        weightStyles[weight],
        className
      )}
      {...props}
    />
  );
}

type TitleLevel = "1" | "2" | "3";

interface TitleProps extends HTMLAttributes<HTMLHeadingElement> {
  level?: TitleLevel;
  weight?: Weight;
}

const titleStyles: Record<TitleLevel, string> = {
  "1": "text-lg",
  "2": "text-base",
  "3": "text-sm",
};

export function Title({
  level = "2",
  weight = "medium",
  className,
  ...props
}: TitleProps) {
  const Tag = level === "1" ? "h2" : level === "2" ? "h3" : "h4";
  return (
    <Tag
      className={cn(
        "tracking-tight text-fg-primary",
        titleStyles[level],
        weightStyles[weight],
        className
      )}
      {...props}
    />
  );
}
