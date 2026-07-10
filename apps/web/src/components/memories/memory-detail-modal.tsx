"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  X, FileText, Star, MessageSquare, Brain, Pencil, Trash2,
  CheckCircle2, Loader, AlertTriangle, Check,
} from "lucide-react";
import type { SearchMemory } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Label } from "@/components/ui/typography";
import { memoryTypeLabel, memoryTypeColor, truncate } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import { useMemoryMutations } from "@/hooks/use-memory-mutations";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface MemoryDetailModalProps {
  memory: SearchMemory | null;
  onClose: () => void;
}

const TYPE_ICONS: Record<string, typeof FileText> = {
  fact: FileText,
  preference: Star,
  episodic: MessageSquare,
};

const TYPE_OPTIONS = [
  { value: "fact", label: "事实" },
  { value: "preference", label: "偏好" },
  { value: "episodic", label: "情节" },
];

export function MemoryDetailModal({ memory: initialMemory, onClose }: MemoryDetailModalProps) {
  const entityId = useAppStore((s) => s.entityId);
  const { updateMemoryMutation, deleteMemoryMutation } = useMemoryMutations(entityId);
  const demoMode = useAppStore((s) => s.demoMode);

  const [memory, setMemory] = useState(initialMemory);
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editType, setEditType] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Reset when memory changes
  const startEditing = useCallback(() => {
    if (!memory) return;
    setEditContent(memory.content);
    setEditSummary(memory.summary);
    setEditType(memory.memory_type);
    setIsEditing(true);
  }, [memory]);

  const cancelEditing = useCallback(() => {
    setIsEditing(false);
    setShowDeleteConfirm(false);
  }, []);

  const handleSave = useCallback(async () => {
    if (!memory) return;

    if (demoMode) {
      // In demo mode, just update local state
      setMemory((prev) =>
        prev
          ? { ...prev, content: editContent, summary: editSummary, memory_type: editType }
          : prev
      );
      setIsEditing(false);
      return;
    }

    const data: Record<string, string> = {};
    if (editContent !== memory.content) data.content = editContent;
    if (editSummary !== memory.summary) data.summary = editSummary;
    if (editType !== memory.memory_type) data.memory_type = editType;

    if (Object.keys(data).length === 0) {
      setIsEditing(false);
      return;
    }

    await updateMemoryMutation.mutateAsync({ id: memory.id, data });
    setMemory((prev) => (prev ? { ...prev, ...data } : prev));
    setIsEditing(false);
  }, [memory, demoMode, editContent, editSummary, editType, updateMemoryMutation]);

  const handleDelete = useCallback(async () => {
    if (!memory) return;
    if (demoMode) {
      onClose();
      return;
    }
    await deleteMemoryMutation.mutateAsync(memory.id);
    onClose();
  }, [memory, demoMode, deleteMemoryMutation, onClose]);

  if (!memory) return null;

  const Icon = TYPE_ICONS[memory.memory_type] ?? Brain;
  const isPending = updateMemoryMutation.isPending || deleteMemoryMutation.isPending;

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
                {isEditing ? (
                  <Select value={editType} onValueChange={setEditType}>
                    <SelectTrigger className="w-28 h-7 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TYPE_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <>
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
                      <Icon className="h-4 w-4" />
                    </div>
                    <Badge className={memoryTypeColor(memory.memory_type)}>
                      {memoryTypeLabel(memory.memory_type)}
                    </Badge>
                  </>
                )}
                {memory.score !== undefined && !isEditing && (
                  <span className="text-xs font-medium text-fg-muted">
                    {Math.round(memory.score * 100)}% confidence
                  </span>
                )}
              </div>
              <h2 className="text-lg font-semibold text-fg-primary">
                {isEditing ? "Edit memory" : "Memory details"}
              </h2>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {!isEditing && (
                <button
                  onClick={startEditing}
                  disabled={isPending}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted hover:bg-surface-hover transition-colors"
                  title="Edit"
                >
                  <Pencil className="h-4 w-4" />
                </button>
              )}
              <button
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted hover:bg-surface-hover transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* ── Body ── */}
          <div className="flex-1 overflow-y-auto p-5">
            {showDeleteConfirm ? (
              <div className="flex flex-col items-center justify-center py-8 space-y-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-900/30">
                  <AlertTriangle className="h-7 w-7 text-red-400" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-fg-primary">Delete this memory?</p>
                  <p className="text-xs text-fg-muted mt-1">This action cannot be undone.</p>
                </div>
                <div className="flex gap-3">
                  <Button variant="ghost" onClick={() => setShowDeleteConfirm(false)} disabled={isPending}>
                    Cancel
                  </Button>
                  <Button
                    onClick={handleDelete}
                    disabled={isPending}
                    className="bg-red-600 hover:bg-red-700 text-white"
                  >
                    {deleteMemoryMutation.isPending ? (
                      <Loader className="h-4 w-4 animate-spin mr-1" />
                    ) : null}
                    Delete
                  </Button>
                </div>
              </div>
            ) : (
              <Tabs defaultValue="content">
                <TabsList className="w-full">
                  <TabsTrigger value="content" className="flex-1">Content</TabsTrigger>
                  <TabsTrigger value="meta" className="flex-1">Metadata</TabsTrigger>
                </TabsList>

                {/* Content tab */}
                <TabsContent value="content" className="space-y-4 pt-4">
                  {isEditing ? (
                    <>
                      <div>
                        <Label level="2" weight="medium" className="text-fg-faint">CONTENT</Label>
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          rows={4}
                          className="mt-1 w-full rounded-lg border border-surface-border bg-surface-card px-3 py-2 text-sm text-fg-primary placeholder:text-fg-faint focus:outline-none focus:ring-2 focus:ring-surface-ring resize-none"
                        />
                      </div>
                      <div>
                        <Label level="2" weight="medium" className="text-fg-faint">SUMMARY</Label>
                        <textarea
                          value={editSummary}
                          onChange={(e) => setEditSummary(e.target.value)}
                          rows={2}
                          className="mt-1 w-full rounded-lg border border-surface-border bg-surface-card px-3 py-2 text-sm text-fg-primary placeholder:text-fg-faint focus:outline-none focus:ring-2 focus:ring-surface-ring resize-none"
                        />
                      </div>
                      <div className="flex justify-end gap-2 pt-2">
                        <Button variant="ghost" size="sm" onClick={cancelEditing} disabled={isPending}>
                          Cancel
                        </Button>
                        <Button size="sm" onClick={handleSave} disabled={isPending || !editContent.trim()}>
                          {updateMemoryMutation.isPending ? (
                            <Loader className="h-4 w-4 animate-spin mr-1" />
                          ) : (
                            <Check className="h-4 w-4 mr-1" />
                          )}
                          Save
                        </Button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div>
                        <Label level="2" weight="medium" className="text-fg-faint">CONTENT</Label>
                        <p className="mt-1 text-sm leading-relaxed text-fg-primary whitespace-pre-wrap">{memory.content}</p>
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
                    </>
                  )}
                </TabsContent>

                {/* Metadata tab */}
                <TabsContent value="meta" className="space-y-3 pt-4">
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

                  {memory.score !== undefined && (
                    <div className="rounded-lg bg-surface-hover/50 p-3">
                      <Label level="3" weight="medium" className="text-fg-faint">CONFIDENCE</Label>
                      <p className="mt-1 text-sm text-fg-primary">{Math.round(memory.score * 100)}%</p>
                    </div>
                  )}

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

                  <Separator />

                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowDeleteConfirm(true)}
                    disabled={isPending}
                    className="w-full border-red-800/50 text-red-400 hover:bg-red-950/30 hover:text-red-300"
                  >
                    <Trash2 className="h-4 w-4 mr-1.5" />
                    Delete memory
                  </Button>
                </TabsContent>
              </Tabs>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
