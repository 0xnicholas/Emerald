"use client";

import type { SearchMemory } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  memoryTypeLabel,
  memoryTypeColor,
  cn,
} from "@/lib/utils";
import { motion } from "motion/react";
import {
  FileText, Star, MessageSquare, BookOpen, Brain, Quote, FolderOpen,
} from "lucide-react";
import { useAppStore } from "@/stores/app";

interface MemoryCardProps {
  memory: SearchMemory;
  onClick?: () => void;
}

const TYPE_ICONS: Record<string, typeof FileText> = {
  fact: FileText,
  preference: Star,
  episodic: MessageSquare,
};

const TYPE_ACCENT: Record<string, string> = {
  fact: "border-t-emerald-500/60 group-hover:border-t-emerald-400",
  preference: "border-t-purple-500/60 group-hover:border-t-purple-400",
  episodic: "border-t-amber-500/60 group-hover:border-t-amber-400",
};

const TYPE_GLOW: Record<string, string> = {
  fact: "shadow-emerald-500/5",
  preference: "shadow-purple-500/5",
  episodic: "shadow-amber-500/5",
};

export function MemoryCard({ memory, onClick }: MemoryCardProps) {
  const Icon = TYPE_ICONS[memory.memory_type] ?? Brain;
  const accent = TYPE_ACCENT[memory.memory_type] ?? "border-t-surface-border";
  const glow = TYPE_GLOW[memory.memory_type] ?? "";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.15 }}
    >
      <div
        onClick={onClick}
        className={cn(
          "group cursor-pointer rounded-[18px] border border-surface-border border-t-4",
          "bg-surface-card/60 shadow-sm backdrop-blur-md",
          "transition-all duration-200 hover:shadow-md",
          accent, glow
        )}
      >
        <div className="p-4">
          {/* Header row */}
          <div className="mb-2.5 flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-hover text-fg-muted shrink-0">
              <Icon className="h-3.5 w-3.5" />
            </div>
            <Badge className={memoryTypeColor(memory.memory_type)}>
              {memoryTypeLabel(memory.memory_type)}
            </Badge>
            {memory.container_tag && memory.container_tag !== "default" && (
              <span className="flex items-center gap-1 rounded-md bg-surface-hover/50 px-1.5 py-0.5 text-[9px] text-fg-faint">
                <FolderOpen className="h-2.5 w-2.5" />
                {memory.container_tag}
              </span>
            )}
          </div>

          {/* Content */}
          <p className="text-sm leading-relaxed text-fg-primary line-clamp-3">
            {memory.content}
          </p>

          {/* Summary */}
          {memory.summary && (
            <div className="mt-2 flex gap-1.5 rounded-lg bg-surface-hover/40 p-2">
              <Quote className="mt-0.5 h-3 w-3 shrink-0 text-fg-faint" />
              <p className="text-xs italic text-fg-muted line-clamp-2">
                {memory.summary}
              </p>
            </div>
          )}

          {/* Tags */}
          {memory.tags && memory.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {memory.tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center px-1.5 py-0.5 rounded-md bg-surface-hover/60 text-[10px] text-fg-faint border border-surface-border/30"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* Footer */}
          <div className="mt-3 flex items-center gap-2 border-t border-surface-border/40 pt-3">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              {memory.source && (
                <span className="flex items-center gap-1 rounded-md bg-surface-hover px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
                  {memory.source === "rag" ? (
                    <BookOpen className="h-3 w-3" />
                  ) : (
                    <Brain className="h-3 w-3" />
                  )}
                  {memory.source === "rag" ? "RAG" : "Memory"}
                </span>
              )}
              {memory.document_title && (
                <span className="truncate text-[10px] text-fg-faint">
                  {memory.document_title}
                </span>
              )}
            </div>

            {/* Confidence bar */}
            {memory.score !== undefined && (
              <div className="flex items-center gap-1.5 shrink-0">
                <div className="w-12 h-1.5 rounded-full bg-surface-hover overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      memory.score >= 0.7 ? "bg-emerald-500" :
                      memory.score >= 0.4 ? "bg-amber-500" : "bg-red-500"
                    )}
                    style={{ width: `${Math.round(memory.score * 100)}%` }}
                  />
                </div>
                <span className="text-[10px] text-fg-faint tabular-nums w-6 text-right">
                  {Math.round(memory.score * 100)}%
                </span>
              </div>
            )}
          </div>

          {/* is_latest indicator */}
          {memory.is_latest === false && (
            <div className="mt-1.5 text-[10px] text-fg-faint text-right">
              Historical version
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
