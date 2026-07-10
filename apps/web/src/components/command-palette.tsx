"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Search, LayoutDashboard, Share2, Settings, Plus,
  MessageSquare, Loader, FileText, Star, Brain, ArrowRight,
} from "lucide-react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { memoryTypeLabel } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import { getClient } from "@/lib/api";
import { getMockSearchResults } from "@/lib/mock-data";
import type { SearchMemory } from "@/lib/types";

// ─── Provider wrapper for the layout ──────────────────────────────────

export function CommandPaletteProvider() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return <CommandPalette open={open} onOpenChange={setOpen} />;
}

const TYPE_ICONS: Record<string, React.ReactNode> = {
  fact: <FileText className="h-3.5 w-3.5" />,
  preference: <Star className="h-3.5 w-3.5" />,
  episodic: <Brain className="h-3.5 w-3.5" />,
};

// ─── Main component ──────────────────────────────────────────────────

type ActionItem = {
  kind: "action";
  id: string;
  label: string;
  description?: string;
  icon: React.ReactNode;
  action: () => void;
};

type MemoryItem = {
  kind: "memory";
  memory: SearchMemory;
};

type PaletteItem = ActionItem | MemoryItem;

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);
  const setChatOpen = useAppStore((s) => s.setChatOpen);

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [searchResults, setSearchResults] = useState<SearchMemory[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = useCallback(() => {
    onOpenChange(false);
    setQuery("");
    setSearchResults([]);
    setSelectedIndex(0);
  }, [onOpenChange]);

  const navigate = useCallback(
    (href: string) => {
      close();
      router.push(href);
    },
    [close, router]
  );

  // Static actions
  const actions: ActionItem[] = useMemo(
    () => [
      {
        kind: "action",
        id: "add-memory",
        label: "Add Memory",
        description: "Save a new note, link, or file",
        icon: <Plus className="h-4 w-4" />,
        action: () => navigate("/?add=note"),
      },
      {
        kind: "action",
        id: "dashboard",
        label: "Dashboard",
        description: "Go to the main dashboard",
        icon: <LayoutDashboard className="h-4 w-4" />,
        action: () => navigate("/"),
      },
      {
        kind: "action",
        id: "memories",
        label: "Memories",
        description: "Browse all saved memories",
        icon: <Search className="h-4 w-4" />,
        action: () => navigate("/memories"),
      },
      {
        kind: "action",
        id: "graph",
        label: "Knowledge Graph",
        description: "Explore memory relationships",
        icon: <Share2 className="h-4 w-4" />,
        action: () => navigate("/graph"),
      },
      {
        kind: "action",
        id: "chat",
        label: "Memory Chat",
        description: "Chat with your memories",
        icon: <MessageSquare className="h-4 w-4" />,
        action: () => {
          close();
          setChatOpen(true);
        },
      },
      {
        kind: "action",
        id: "settings",
        label: "Settings",
        description: "Configure your connection",
        icon: <Settings className="h-4 w-4" />,
        action: () => navigate("/settings"),
      },
    ],
    [close, navigate, setChatOpen]
  );

  // Search memories
  useEffect(() => {
    if (!query.trim()) {
      setSearchResults([]);
      setSelectedIndex(0);
      return;
    }

    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(async () => {
      setIsSearching(true);
      try {
        if (demoMode) {
          const data = getMockSearchResults(query);
          setSearchResults(data.results.slice(0, 8));
        } else {
          const data = await getClient().search(query, entityId, {
            searchMode: "hybrid",
            topK: 8,
          });
          setSearchResults(data.results);
        }
      } catch {
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 200);

    setSelectedIndex(0);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, entityId, demoMode]);

  // Build the flat items list
  const allItems: PaletteItem[] = useMemo(() => {
    const items: PaletteItem[] = [...actions];
    if (query.trim() && searchResults.length > 0) {
      items.push(
        ...searchResults.map((m) => ({ kind: "memory" as const, memory: m }))
      );
    }
    return items;
  }, [actions, query, searchResults]);

  // Clamp selected index
  useEffect(() => {
    if (selectedIndex >= allItems.length && allItems.length > 0) {
      setSelectedIndex(allItems.length - 1);
    }
  }, [allItems.length, selectedIndex]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, allItems.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = allItems[selectedIndex];
        if (!item) return;
        if (item.kind === "action") {
          item.action();
        } else if (item.kind === "memory") {
          // Navigate to memories page with the query
          close();
          router.push("/memories");
        }
      }
    },
    [allItems, selectedIndex, close, router]
  );

  // Auto-focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // ⌘K listener when this instance is the active one
  // (global listener is handled by CommandPaletteProvider)



  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-[580px] p-0 gap-0 overflow-hidden rounded-[18px] border-surface-border bg-surface-card/95 backdrop-blur-xl shadow-[0_20px_60px_rgba(0,0,0,0.5)]"
        onKeyDown={handleKeyDown}
        hideCloseButton
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-border/50">
          <Search className="h-4 w-4 text-fg-muted shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search memories or jump to..."
            className="flex-1 bg-transparent text-sm text-fg-primary placeholder:text-fg-faint focus:outline-none"
          />
          {isSearching && <Loader className="h-3.5 w-3.5 animate-spin text-fg-muted shrink-0" />}
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded-md bg-surface-hover text-[10px] font-mono text-fg-faint border border-surface-border/50">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[400px] overflow-y-auto p-2" role="listbox">
          {allItems.length === 0 && query.trim() ? (
            <div className="flex flex-col items-center justify-center py-10 text-fg-subtle">
              <Search className="h-8 w-8 mb-2 opacity-40" />
              <p className="text-sm">No results found</p>
              <p className="text-xs mt-0.5">Try a different search term</p>
            </div>
          ) : (
            <>
              {/* Actions section (only when query is empty or short) */}
              {(!query.trim() || query.trim().length < 2) && (
                <div>
                  <div className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-fg-faint font-medium">
                    Quick actions
                  </div>
                  {actions.map((item, i) => (
                    <PaletteRow
                      key={item.id}
                      item={item}
                      selected={selectedIndex === i}
                      index={i}
                      onClick={item.action}
                    />
                  ))}
                </div>
              )}

              {/* Search results */}
              {query.trim() && searchResults.length > 0 && (
                <div>
                  <div className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-fg-faint font-medium mt-1">
                    Memories
                  </div>
                  {searchResults.map((memory, i) => {
                    const globalIndex = actions.length + i;
                    return (
                      <PaletteRow
                        key={memory.id}
                        item={{ kind: "memory", memory }}
                        selected={selectedIndex === globalIndex}
                        index={globalIndex}
                        onClick={() => {
                          close();
                          router.push("/memories");
                        }}
                      />
                    );
                  })}
                  <div className="px-2 py-2 text-xs text-fg-faint text-center">
                    <ArrowRight className="h-3 w-3 inline mr-1" />
                    Press Enter to go to full search
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PaletteRow({
  item,
  selected,
  index,
  onClick,
}: {
  item: PaletteItem;
  selected: boolean;
  index: number;
  onClick: () => void;
}) {
  return (
    <button
      role="option"
      aria-selected={selected}
      onMouseEnter={() => {}}
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 w-full px-3 py-2.5 rounded-xl text-left transition-colors cursor-pointer",
        selected
          ? "bg-brand-accent-subtle text-brand-accent"
          : "text-fg-primary hover:bg-surface-hover"
      )}
    >
      {item.kind === "action" ? (
        <>
          <div
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-lg shrink-0",
              selected ? "bg-brand-accent/20" : "bg-surface-hover text-fg-muted"
            )}
          >
            {item.icon}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">{item.label}</p>
            {item.description && (
              <p className="text-xs text-fg-muted truncate">{item.description}</p>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-hover text-fg-muted shrink-0">
            {TYPE_ICONS[item.memory.memory_type] ?? <Brain className="h-3.5 w-3.5" />}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-fg-primary truncate">{item.memory.content}</p>
            <p className="text-xs text-fg-muted truncate">
              {memoryTypeLabel(item.memory.memory_type)}
              {item.memory.score !== undefined && (
                <> · {Math.round(item.memory.score * 100)}%</>
              )}
            </p>
          </div>
        </>
      )}

      {selected && (
        <kbd className="shrink-0 flex items-center px-1.5 py-0.5 rounded-md bg-surface-hover text-[10px] font-mono text-fg-faint border border-surface-border/50">
          ↵
        </kbd>
      )}
    </button>
  );
}
