import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateStr?: string): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

export function memoryTypeLabel(type: string): string {
  const map: Record<string, string> = {
    fact: "事实",
    preference: "偏好",
    episodic: "情节",
  };
  return map[type] ?? type;
}

export function memoryTypeColor(type: string): string {
  const map: Record<string, string> = {
    fact:
      "bg-memory-fact-bg text-memory-fact",
    preference:
      "bg-memory-preference-bg text-memory-preference",
    episodic:
      "bg-memory-episodic-bg text-memory-episodic",
  };
  return map[type] ?? "bg-surface-hover text-fg-muted";
}

export function confidenceColor(score: number): string {
  if (score >= 0.7) return "text-green-600 dark:text-green-400";
  if (score >= 0.4) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}
