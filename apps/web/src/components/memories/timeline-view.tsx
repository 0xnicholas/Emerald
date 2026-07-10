"use client";

import { useMemo } from "react";
import { motion } from "motion/react";
import {
  Calendar, FileText, Star, MessageSquare, Brain, Clock,
} from "lucide-react";
import type { SearchMemory } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";

interface TimelineViewProps {
  memories: SearchMemory[];
  onMemoryClick?: (memory: SearchMemory) => void;
  emptyMessage?: string;
}

const TYPE_ICONS: Record<string, typeof FileText> = {
  fact: FileText,
  preference: Star,
  episodic: MessageSquare,
};

type DateGroup = {
  label: string;
  memories: SearchMemory[];
};

function formatTime(dateStr: string | undefined): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function groupByDate(memories: SearchMemory[]): DateGroup[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const thisWeekStart = new Date(today);
  thisWeekStart.setDate(thisWeekStart.getDate() - thisWeekStart.getDay());
  const lastWeekStart = new Date(thisWeekStart);
  lastWeekStart.setDate(lastWeekStart.getDate() - 7);

  const groups: Record<string, SearchMemory[]> = {
    "Today": [],
    "Yesterday": [],
    "This Week": [],
    "Last Week": [],
    "Older": [],
  };

  for ( const m of memories) {
    const created = m.created_at ? new Date(m.created_at) : today;
    created.setHours(0, 0, 0, 0);
    if (created.getTime() === today.getTime()) {
      groups["Today"].push(m);
    } else if (created.getTime() === yesterday.getTime()) {
      groups["Yesterday"].push(m);
    } else if (created >= thisWeekStart) {
      groups["This Week"].push(m);
    } else if (created >= lastWeekStart) {
      groups["Last Week"].push(m);
    } else {
      groups["Older"].push(m);
    }
  }

  const order = ["Today", "Yesterday", "This Week", "Last Week", "Older"];
  return order
    .map((label) => ({ label, memories: groups[label] }))
    .filter((g) => g.memories.length > 0);
}

export function TimelineView({ memories, onMemoryClick, emptyMessage = "No memories yet" }: TimelineViewProps) {
  const groups = useMemo(() => groupByDate(memories), [memories]);

  if (memories.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-fg-subtle">
        <Calendar className="mb-3 h-10 w-10 opacity-40" />
        <p className="text-sm font-medium">{emptyMessage}</p>
        <p className="mt-1 text-xs">Memories will appear here as you add them</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {groups.map((group) => (
        <div key={group.label}>
          {/* Date group header */}
          <div className="flex items-center gap-3 mb-4">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-accent/20">
                <Calendar className="h-3.5 w-3.5 text-brand-accent" />
              </div>
              <h3 className="text-sm font-semibold text-fg-primary">{group.label}</h3>
            </div>
            <div className="flex-1 h-px bg-surface-border/50" />
            <span className="text-xs text-fg-faint">{group.memories.length}</span>
          </div>

          {/* Timeline entries */}
          <div className="relative pl-8 space-y-4">
            {/* Vertical line */}
            <div className="absolute left-[13px] top-2 bottom-2 w-px bg-surface-border/60" />

            {group.memories.map((memory, i) => {
              const Icon = TYPE_ICONS[memory.memory_type] ?? Brain;
              const colorClass = memory.memory_type === "fact"
                ? "border-emerald-500/30 bg-emerald-500/10"
                : memory.memory_type === "preference"
                  ? "border-purple-500/30 bg-purple-500/10"
                  : "border-amber-500/30 bg-amber-500/10";

              return (
                <motion.div
                  key={memory.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2, delay: i * 0.02 }}
                  className="group relative"
                >
                  {/* Timeline dot */}
                  <div className={`absolute -left-[21px] top-3 w-3.5 h-3.5 rounded-full border-2 ${colorClass}`} />

                  {/* Content card */}
                  <div
                    onClick={() => onMemoryClick?.(memory)}
                    className="rounded-xl border border-surface-border bg-surface-card/60 p-3.5 shadow-sm hover:shadow-md hover:border-surface-ring/30 transition-all cursor-pointer backdrop-blur-md"
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-hover text-fg-muted shrink-0">
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge className={memoryTypeColor(memory.memory_type)}>
                            {memoryTypeLabel(memory.memory_type)}
                          </Badge>
                          {memory.created_at && (
                            <span className="flex items-center gap-1 text-[10px] text-fg-faint">
                              <Clock className="h-3 w-3" />
                              {formatTime(memory.created_at)}
                            </span>
                          )}
                          {memory.tags && memory.tags.length > 0 && (
                            <div className="flex gap-1 ml-auto">
                              {memory.tags.slice(0, 2).map((tag) => (
                                <span
                                  key={tag}
                                  className="px-1.5 py-0.5 rounded-md bg-surface-hover text-[9px] text-fg-faint"
                                >
                                  {tag}
                                </span>
                              ))}
                              {memory.tags.length > 2 && (
                                <span className="text-[9px] text-fg-faint">+{memory.tags.length - 2}</span>
                              )}
                            </div>
                          )}
                        </div>
                        <p className="text-sm leading-relaxed text-fg-primary">{memory.content}</p>
                        {memory.summary && (
                          <p className="mt-1 text-xs text-fg-muted">{memory.summary}</p>
                        )}
                      </div>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
