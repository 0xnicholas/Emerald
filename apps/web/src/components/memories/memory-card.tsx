"use client";

import type { SearchMemory } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  memoryTypeLabel,
  memoryTypeColor,
  confidenceColor,
  truncate,
} from "@/lib/utils";
import { motion } from "motion/react";
import {
  FileText,
  Star,
  MessageSquare,
  BookOpen,
  Brain,
  Quote,
} from "lucide-react";

interface MemoryCardProps {
  memory: SearchMemory;
  onClick?: () => void;
}

const typeIcons: Record<string, typeof FileText> = {
  fact: FileText,
  preference: Star,
  episodic: MessageSquare,
};

const typeAccentColors: Record<string, string> = {
  fact: "border-t-emerald-400 group-hover:border-t-emerald-500",
  preference:
    "border-t-purple-400 group-hover:border-t-purple-500",
  episodic: "border-t-amber-400 group-hover:border-t-amber-500",
};

export function MemoryCard({ memory, onClick }: MemoryCardProps) {
  const Icon = typeIcons[memory.memory_type] ?? Brain;
  const borderColor =
    typeAccentColors[memory.memory_type] ??
    "border-t-zinc-400 group-hover:border-t-zinc-500";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2 }}
    >
      <div
        onClick={onClick}
        className={`group cursor-pointer rounded-xl border border-zinc-100 border-t-4 bg-white shadow-sm transition-all hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900 ${borderColor}`}
      >
        {/* Top accent bar */}
        <div className="p-4">
          {/* Header row */}
          <div className="mb-2.5 flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
              <Icon className="h-3.5 w-3.5" />
            </div>
            <Badge className={memoryTypeColor(memory.memory_type)}>
              {memoryTypeLabel(memory.memory_type)}
            </Badge>
            {memory.score !== undefined && (
              <span
                className={`ml-auto text-xs font-medium ${confidenceColor(memory.score)}`}
              >
                {Math.round(memory.score * 100)}%
              </span>
            )}
          </div>

          {/* Content */}
          <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
            {truncate(memory.content, 180)}
          </p>

          {/* Summary */}
          {memory.summary && (
            <div className="mt-2 flex gap-1.5 rounded-md bg-zinc-50 p-2 dark:bg-zinc-800/50">
              <Quote className="mt-0.5 h-3 w-3 shrink-0 text-zinc-400" />
              <p className="text-xs italic text-zinc-500 dark:text-zinc-400">
                {truncate(memory.summary, 100)}
              </p>
            </div>
          )}

          {/* Footer */}
          <div className="mt-3 flex items-center gap-2 border-t border-zinc-100 pt-3 dark:border-zinc-800">
            {memory.source && (
              <span className="flex items-center gap-1 rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                {memory.source === "rag" ? (
                  <BookOpen className="h-3 w-3" />
                ) : (
                  <Brain className="h-3 w-3" />
                )}
                {memory.source === "rag" ? "RAG" : "记忆"}
              </span>
            )}
            {memory.document_title && (
              <span className="truncate text-[10px] text-zinc-400">
                📄 {memory.document_title}
              </span>
            )}
            {memory.is_latest === false && (
              <span className="ml-auto text-[10px] text-zinc-400">
                历史版本
              </span>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
