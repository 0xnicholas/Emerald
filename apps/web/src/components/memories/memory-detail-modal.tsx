"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  X, FileText, Star, MessageSquare, Brain, Clock, Tag, BookOpen,
  CheckCircle2, TrendingUp, Hash, ArrowUpRight,
} from "lucide-react";
import type { SearchMemory } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Label } from "@/components/ui/typography";
import { memoryTypeLabel, memoryTypeColor, truncate } from "@/lib/utils";

interface MemoryDetailModalProps {
  memory: SearchMemory | null;
  onClose: () => void;
}

const typeIcons: Record<string, typeof FileText> = {
  fact: FileText,
  preference: Star,
  episodic: MessageSquare,
};

export function MemoryDetailModal({ memory, onClose }: MemoryDetailModalProps) {
  if (!memory) return null;

  const Icon = typeIcons[memory.memory_type] ?? Brain;

  // Mock related memories for demo
  const relatedMemories: SearchMemory[] = [];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          transition={{ duration: 0.15 }}
          className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-[18px] border border-surface-border bg-surface-card/80 shadow-[0_12px_40px_rgba(0,0,0,0.34)] backdrop-blur-xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* ── Header ── */}
          <div className="flex items-start justify-between gap-4 border-b border-surface-border/50 p-5">
            <div className="flex-1 space-y-2">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
                  <Icon className="h-4 w-4" />
                </div>
                <Badge className={memoryTypeColor(memory.memory_type)}>
                  {memoryTypeLabel(memory.memory_type)}
                </Badge>
                {memory.score !== undefined && (
                  <span className="text-xs font-medium text-fg-muted">
                    {Math.round(memory.score * 100)}% confidence
                  </span>
                )}
              </div>
              <h2 className="text-lg font-semibold text-fg-primary">Memory details</h2>
            </div>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted hover:bg-surface-hover transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* ── Tabs ── */}
          <div className="flex-1 overflow-y-auto p-5">
            <Tabs defaultValue="content">
              <TabsList className="w-full">
                <TabsTrigger value="content" className="flex-1">Content</TabsTrigger>
                <TabsTrigger value="related" className="flex-1">Related ({relatedMemories.length})</TabsTrigger>
                <TabsTrigger value="meta" className="flex-1">Metadata</TabsTrigger>
              </TabsList>

              {/* Content tab */}
              <TabsContent value="content" className="space-y-4">
                <div>
                  <Label level="2" weight="medium" className="text-fg-faint">CONTENT</Label>
                  <p className="mt-1 text-sm leading-relaxed text-fg-primary">{memory.content}</p>
                </div>

                {memory.summary && (
                  <>
                    <Separator />
                    <div>
                      <Label level="2" weight="medium" className="text-fg-faint">SUMMARY</Label>
                      <div className="mt-1 flex gap-2 rounded-lg bg-surface-hover/50 p-3">
                        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-fg-faint" />
                        <p className="text-sm text-fg-muted">{memory.summary}</p>
                      </div>
                    </div>
                  </>
                )}
              </TabsContent>

              {/* Related tab */}
              <TabsContent value="related">
                {relatedMemories.length > 0 ? (
                  <div className="space-y-1.5">
                    {relatedMemories.map((r) => (
                      <div key={r.id} className="flex items-start gap-2 rounded-lg p-2 hover:bg-surface-hover">
                        <Brain className="mt-0.5 h-4 w-4 shrink-0 text-fg-faint" />
                        <p className="text-xs text-fg-muted">{truncate(r.content, 120)}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-12 text-fg-subtle">
                    <Brain className="mb-2 h-8 w-8 opacity-40" />
                    <p className="text-sm">No related memories found</p>
                  </div>
                )}
              </TabsContent>

              {/* Metadata tab */}
              <TabsContent value="meta">
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg bg-surface-hover/50 p-3">
                      <Label level="3" weight="medium" className="text-fg-faint">STATUS</Label>
                      <p className="mt-1 text-sm text-fg-primary">
                        {memory.is_latest ? "Latest version" : "Historical"}
                      </p>
                    </div>
                    <div className="rounded-lg bg-surface-hover/50 p-3">
                      <Label level="3" weight="medium" className="text-fg-faint">SOURCE</Label>
                      <p className="mt-1 text-sm text-fg-primary">
                        {memory.source === "rag" ? "RAG Document" : "Memory Graph"}
                      </p>
                    </div>
                  </div>

                  {memory.document_title && (
                    <div className="rounded-lg bg-surface-hover/50 p-3">
                      <Label level="3" weight="medium" className="text-fg-faint">DOCUMENT</Label>
                      <p className="mt-1 text-sm text-fg-primary">{memory.document_title}</p>
                    </div>
                  )}

                  <div className="rounded-lg bg-surface-hover/50 p-3">
                    <Label level="3" weight="medium" className="text-fg-faint">ID</Label>
                    <code className="mt-1 block text-xs text-fg-muted font-mono">{memory.id}</code>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
