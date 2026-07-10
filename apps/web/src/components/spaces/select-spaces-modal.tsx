"use client";

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import {
  X, Search, Clock, Plus, Trash2, Pencil, Check, Loader,
} from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import { useSelectedSpace, DEFAULT_SPACE_TAG } from "@/hooks/use-space";
import { useContainerTags } from "@/hooks/use-container-tags";
import { useProjectMutations } from "@/hooks/use-project-mutations";
import { compareSpaces, getSpaceLabel } from "@/lib/spaces";
import { SpaceGlyph } from "./space-glyph";
import { AddSpaceModal } from "./add-space-modal";
import type { Space } from "@/lib/types";

const RECENTS_KEY = "emerald:space-recents";
const RECENTS_MAX = 5;

interface SelectSpacesModalProps {
  isOpen: boolean;
  onClose: () => void;
}

function readRecents(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENTS_KEY);
    return raw ? JSON.parse(raw).filter((x: unknown) => typeof x === "string") : [];
  } catch { return []; }
}

function pushRecent(tag: string) {
  try {
    const next = [tag, ...readRecents().filter((t) => t !== tag)].slice(0, RECENTS_MAX);
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next));
  } catch { /* noop */ }
}

export function SelectSpacesModal({ isOpen, onClose }: SelectSpacesModalProps) {
  const entityId = useAppStore((s) => s.entityId);
  const { selectedSpaceTag, setSelectedSpaceTag } = useSelectedSpace();
  const { spaces, isLoading } = useContainerTags();
  const { deleteSpaceMutation, updateSpaceMutation } = useProjectMutations();

  const [searchQuery, setSearchQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [isBulkMode, setIsBulkMode] = useState(false);
  const [bulkTags, setBulkTags] = useState<Set<string>>(new Set());
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const editRef = useRef<HTMLInputElement>(null);

  const sortedSpaces = useMemo(() => [...spaces].sort(compareSpaces), [spaces]);

  const filteredSpaces = useMemo(() => {
    if (!searchQuery.trim()) return sortedSpaces;
    const q = searchQuery.toLowerCase();
    return sortedSpaces.filter(
      (s) => s.name.toLowerCase().includes(q) || s.containerTag.toLowerCase().includes(q)
    );
  }, [sortedSpaces, searchQuery]);

  const recents = useMemo(
    () => readRecents().map((tag) => spaces.find((s) => s.containerTag === tag)).filter(Boolean) as Space[],
    [spaces]
  );

  const mainList = useMemo(
    () => filteredSpaces.filter((s) => !recents.some((r) => r.containerTag === s.containerTag)),
    [filteredSpaces, recents]
  );

  const handleSelect = useCallback(
    (tag: string) => {
      if (isBulkMode) return;
      setSelectedSpaceTag(tag);
      pushRecent(tag);
      onClose();
    },
    [isBulkMode, setSelectedSpaceTag, onClose]
  );

  const handleBulkToggle = useCallback((tag: string, shiftKey = false) => {
    setBulkTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  }, []);

  const handleBulkDelete = useCallback(async () => {
    for (const tag of bulkTags) {
      await deleteSpaceMutation.mutateAsync({ tag });
    }
    setBulkTags(new Set());
    setIsBulkMode(false);
  }, [bulkTags, deleteSpaceMutation]);

  const startEditing = useCallback((space: Space) => {
    setEditingTag(space.containerTag);
    setEditName(space.name);
  }, []);

  const saveEditing = useCallback(() => {
    if (editingTag && editName.trim()) {
      updateSpaceMutation.mutate({ tag: editingTag, name: editName.trim() });
    }
    setEditingTag(null);
  }, [editingTag, editName, updateSpaceMutation]);

  useEffect(() => {
    if (editingTag) editRef.current?.focus();
  }, [editingTag]);

  useEffect(() => {
    if (!isOpen) {
      setSearchQuery("");
      setEditingTag(null);
      setIsBulkMode(false);
      setBulkTags(new Set());
    }
  }, [isOpen]);

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="sm:max-w-[500px] p-0 gap-0 overflow-hidden rounded-[18px] border-surface-border bg-surface-card/95 backdrop-blur-xl">
          <div className="flex items-center justify-between p-4 border-b border-surface-border/50">
            <div>
              <DialogTitle className="text-base font-semibold text-fg-primary">
                {isBulkMode ? "Delete Spaces" : "Select Space"}
              </DialogTitle>
              <p className="text-xs text-fg-muted mt-0.5">
                {isBulkMode ? "Choose spaces to permanently delete" : "Filter your memories by space"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {!isBulkMode && (
                <button
                  onClick={() => setIsBulkMode(true)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-full bg-surface-hover text-xs text-fg-muted hover:text-fg-primary transition-colors"
                >
                  <Trash2 className="h-3 w-3" />
                  Bulk delete
                </button>
              )}
              <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-hover text-fg-muted hover:text-fg-primary">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <div className="p-4 space-y-3">
            {!isBulkMode && (
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-fg-muted" />
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search spaces..."
                  className="w-full rounded-xl bg-surface-hover border border-surface-border pl-9 pr-3 py-2 text-sm text-fg-primary placeholder:text-fg-faint focus:outline-none focus:ring-1 focus:ring-surface-ring"
                />
              </div>
            )}

            {isLoading ? (
              <div className="flex justify-center py-8">
                <Loader className="h-5 w-5 animate-spin text-fg-muted" />
              </div>
            ) : (
              <div className="max-h-80 overflow-y-auto space-y-0.5 scrollbar-thin">
                {/* Recently used */}
                {!searchQuery && !isBulkMode && recents.length > 0 && (
                  <>
                    <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] uppercase tracking-wider text-fg-faint">
                      <Clock className="h-3 w-3" />
                      Recently used
                    </div>
                    {recents.map((space) => renderRow(space))}
                    <div className="my-1.5 mx-2 h-px bg-surface-border/50" />
                  </>
                )}

                {/* Main list */}
                {mainList.length > 0 ? (
                  mainList.map((space) => renderRow(space))
                ) : (
                  <p className="text-center text-sm text-fg-muted py-8">No spaces found</p>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-surface-border/50 p-3">
            {isBulkMode ? (
              <>
                <span className="text-xs text-fg-muted">
                  {bulkTags.size === 0 ? "No spaces selected" : `${bulkTags.size} selected`}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setIsBulkMode(false); setBulkTags(new Set()); }}
                    className="text-xs text-fg-muted hover:text-fg-primary px-3 py-1.5"
                  >
                    Cancel
                  </button>
                  <Button
                    size="sm"
                    disabled={bulkTags.size === 0 || deleteSpaceMutation.isPending}
                    onClick={handleBulkDelete}
                    className="bg-red-600 hover:bg-red-700 text-white text-xs"
                  >
                    {deleteSpaceMutation.isPending ? <Loader className="h-3 w-3 animate-spin mr-1" /> : null}
                    Delete selected
                  </Button>
                </div>
              </>
            ) : (
              <>
                <span />
                <button
                  onClick={() => setShowCreate(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-hover text-xs text-fg-primary hover:bg-surface-skeleton transition-colors"
                >
                  <Plus className="h-3.5 w-3.5" />
                  New space
                </button>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <AddSpaceModal isOpen={showCreate} onClose={() => setShowCreate(false)} />
    </>
  );

  function renderRow(space: Space) {
    const isSelected = selectedSpaceTag === space.containerTag;
    const isDefault = space.containerTag === DEFAULT_SPACE_TAG;
    const isEditing = editingTag === space.containerTag;

    if (isEditing) {
      return (
        <div key={space.containerTag} className="flex items-center gap-2 px-2 py-2">
          <SpaceGlyph emoji={space.emoji} size={18} />
          <input
            ref={editRef}
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveEditing();
              if (e.key === "Escape") setEditingTag(null);
            }}
            className="flex-1 rounded-lg bg-surface-hover border border-surface-border px-2 py-1 text-sm text-fg-primary focus:outline-none focus:ring-1 focus:ring-surface-ring"
          />
          <button onClick={saveEditing} className="p-1 text-brand-accent hover:bg-surface-hover rounded cursor-pointer">
            <Check className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => setEditingTag(null)} className="p-1 text-fg-muted hover:bg-surface-hover rounded cursor-pointer">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      );
    }

    return (
      <div
        key={space.containerTag}
        className={cn(
          "group flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors cursor-pointer",
          isBulkMode
            ? "hover:bg-surface-hover"
            : isSelected
              ? "bg-surface-hover"
              : "hover:bg-surface-hover/50",
          isBulkMode && isDefault && "opacity-40 cursor-not-allowed"
        )}
        onClick={() => {
          if (isBulkMode) {
            if (!isDefault) handleBulkToggle(space.containerTag);
          } else {
            handleSelect(space.containerTag);
          }
        }}
      >
        {/* Radio / Checkbox */}
        <div className={cn(
          "w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors",
          isBulkMode
            ? bulkTags.has(space.containerTag)
              ? "border-red-400 bg-red-400/10"
              : "border-fg-faint"
            : isSelected
              ? "border-brand-accent"
              : "border-fg-faint"
        )}>
          {isBulkMode ? (
            bulkTags.has(space.containerTag) && <Check className="h-3 w-3 text-red-300" />
          ) : (
            isSelected && <div className="w-2 h-2 rounded-full bg-brand-accent" />
          )}
        </div>

        <SpaceGlyph emoji={space.emoji} size={20} />
        <span className="flex-1 min-w-0 text-sm text-fg-primary truncate">{space.name}</span>
        {space.memoryCount > 0 && (
          <span className="text-xs text-fg-faint tabular-nums">{space.memoryCount}</span>
        )}

        {/* Edit / Delete buttons */}
        {!isBulkMode && !isDefault && (
          <>
            <button
              onClick={(e) => { e.stopPropagation(); startEditing(space); }}
              className="opacity-0 group-hover:opacity-100 p-1 rounded text-fg-muted hover:bg-surface-hover transition-all cursor-pointer"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                deleteSpaceMutation.mutate({ tag: space.containerTag });
              }}
              className="opacity-0 group-hover:opacity-100 p-1 rounded text-red-400 hover:bg-surface-hover transition-all cursor-pointer"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    );
  }
}
