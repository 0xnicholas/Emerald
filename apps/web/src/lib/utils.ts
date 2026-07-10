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
    fact: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    preference:
      "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
    episodic:
      "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  };
  return map[type] ?? "bg-gray-100 text-gray-800";
}

export function confidenceColor(score: number): string {
  if (score >= 0.7) return "text-green-600 dark:text-green-400";
  if (score >= 0.4) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}
