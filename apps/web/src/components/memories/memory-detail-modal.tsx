"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, Clock, CheckCircle2, TrendingUp, FileText } from "lucide-react";
import type { SearchMemory } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  memoryTypeLabel,
  memoryTypeColor,
  formatDate,
  confidenceColor,
} from "@/lib/utils";

interface MemoryDetailModalProps {
  memory: SearchMemory | null;
  onClose: () => void;
}

export function MemoryDetailModal({ memory, onClose }: MemoryDetailModalProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!memory) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          transition={{ duration: 0.15 }}
          className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-4 border-b border-zinc-200 p-5 dark:border-zinc-700">
            <div className="flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={memoryTypeColor(memory.memory_type)}>
                  {memoryTypeLabel(memory.memory_type)}
                </Badge>
                {memory.score !== undefined && (
                  <span
                    className={`text-sm font-medium ${confidenceColor(memory.score)}`}
                  >
                    {Math.round(memory.score * 100)}% 置信度
                  </span>
                )}
                {memory.source && (
                  <Badge className="bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    {memory.source}
                  </Badge>
                )}
              </div>
              <h2 className="text-lg font-semibold">记忆详情</h2>
            </div>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-5 w-5" />
            </Button>
          </div>

          {/* Content */}
          <div className="space-y-5 p-5">
            {/* Memory content */}
            <div>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                内容
              </h3>
              <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
                {memory.content}
              </p>
            </div>

            {/* Summary */}
            {memory.summary && (
              <div>
                <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  <FileText className="h-3.5 w-3.5" />
                  摘要
                </h3>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {memory.summary}
                </p>
              </div>
            )}

            {/* Metadata grid */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  状态
                </h3>
                <p className="text-sm">
                  {memory.is_latest ? (
                    <span className="text-emerald-600 dark:text-emerald-400">
                      最新版本
                    </span>
                  ) : (
                    <span className="text-zinc-500">历史版本</span>
                  )}
                </p>
              </div>

              <div>
                <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  <TrendingUp className="h-3.5 w-3.5" />
                  类型
                </h3>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {memory.source === "rag" ? "RAG 文档" : "记忆"}
                </p>
              </div>

              {memory.document_title && (
                <div className="col-span-2">
                  <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                    📄 文档
                  </h3>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    {memory.document_title}
                    {memory.document_id && (
                      <span className="ml-2 text-xs text-zinc-400">
                        ({memory.document_id})
                      </span>
                    )}
                  </p>
                </div>
              )}
            </div>

            {/* ID reference */}
            <div className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-800/50">
              <p className="text-xs text-zinc-400">
                ID: <code className="font-mono">{memory.id}</code>
              </p>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
