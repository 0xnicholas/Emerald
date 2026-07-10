"use client";

import type { SearchMemory } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  memoryTypeLabel,
  memoryTypeColor,
  confidenceColor,
  truncate,
  formatDate,
} from "@/lib/utils";
import { motion } from "motion/react";

interface MemoryCardProps {
  memory: SearchMemory;
  onClick?: () => void;
}

export function MemoryCard({ memory, onClick }: MemoryCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
    >
      <Card
        className="cursor-pointer transition-shadow hover:shadow-md"
        onClick={onClick}
      >
        <CardContent className="p-4">
          <div className="mb-2 flex items-center gap-2">
            <Badge className={memoryTypeColor(memory.memory_type)}>
              {memoryTypeLabel(memory.memory_type)}
            </Badge>
            {memory.score !== undefined && (
              <span
                className={`text-xs font-medium ${confidenceColor(memory.score)}`}
              >
                {Math.round(memory.score * 100)}%
              </span>
            )}
            {memory.source && (
              <Badge className="bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                {memory.source}
              </Badge>
            )}
          </div>
          <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
            {truncate(memory.content, 200)}
          </p>
          {memory.summary && (
            <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
              {truncate(memory.summary, 120)}
            </p>
          )}
          {memory.document_title && (
            <p className="mt-2 text-xs text-zinc-400">
              📄 {memory.document_title}
            </p>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
