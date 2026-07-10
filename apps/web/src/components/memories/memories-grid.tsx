"use client";

import { useMemo } from "react";
import type { SearchMemory } from "@/lib/types";
import { MemoryCard } from "./memory-card";
import { Brain } from "lucide-react";

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
  // Split into columns for masonry layout
  const columns = useMemo(() => {
    const cols: SearchMemory[][] = [[], [], []];
    memories.forEach((mem, i) => {
      cols[i % 3].push(mem);
    });
    return cols;
  }, [memories]);

  if (memories.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-zinc-400">
        <Brain className="mb-3 h-10 w-10" />
        <p className="text-lg font-medium">{emptyMessage}</p>
        <p className="mt-1 text-sm">
          添加内容到 Emerald 记忆引擎，或调整搜索条件
        </p>
      </div>
    );
  }

  return (
    <div className="hidden gap-3 md:columns-2 lg:columns-3 xl:columns-4">
      {memories.map((mem) => (
        <div key={mem.id} className="mb-3 break-inside-avoid">
          <MemoryCard
            memory={mem}
            onClick={() => onMemoryClick?.(mem)}
          />
        </div>
      ))}
    </div>
  );
}
