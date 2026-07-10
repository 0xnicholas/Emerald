"use client";

import type { SearchMemory } from "@/lib/types";
import { MemoryCard } from "./memory-card";

interface MemoriesGridProps {
  memories: SearchMemory[];
  onMemoryClick?: (memory: SearchMemory) => void;
  emptyMessage?: string;
}

export function MemoriesGrid({
  memories,
  onMemoryClick,
  emptyMessage = "暂无记忆数据",
}: MemoriesGridProps) {
  if (memories.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-400">
        <p className="text-lg">{emptyMessage}</p>
        <p className="mt-1 text-sm">
          添加内容到 Emerald 记忆引擎，或调整搜索条件
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {memories.map((mem) => (
        <MemoryCard
          key={mem.id}
          memory={mem}
          onClick={() => onMemoryClick?.(mem)}
        />
      ))}
    </div>
  );
}
