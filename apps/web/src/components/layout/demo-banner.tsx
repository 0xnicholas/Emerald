"use client";

import { useAppStore } from "@/stores/app";
import { EyeIcon, X } from "lucide-react";

export function DemoBanner() {
  const demoMode = useAppStore((s) => s.demoMode);
  const setDemoMode = useAppStore((s) => s.setDemoMode);

  if (!demoMode) return null;

  return (
    <div className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
      <div className="flex items-center gap-2">
        <EyeIcon className="h-4 w-4" />
        <span>
          Demo 预览模式 — 展示的是模拟数据，连接后端后可查看真实记忆
        </span>
      </div>
      <button
        onClick={() => setDemoMode(false)}
        className="rounded p-1 hover:bg-amber-100 dark:hover:bg-amber-900/50"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
