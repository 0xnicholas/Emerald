"use client";

import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { SearchBar } from "@/components/search/search-bar";
import { MemoriesGrid } from "@/components/memories/memories-grid";
import { TimelineView } from "@/components/memories/timeline-view";
import { MemoryDetailModal } from "@/components/memories/memory-detail-modal";
import { DemoBanner } from "@/components/layout/demo-banner";
import { getClient } from "@/lib/api";
import type { SearchMemory } from "@/lib/types";
import { getMockSearchResults } from "@/lib/mock-data";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  ListFilter,
  RotateCcw,
  Brain,
  BookOpen,
  Clock,
  Filter,
  X,
  Search,
  LayoutList,
  Grid3X3,
} from "lucide-react";

type FilterMode = "all" | "memory" | "rag";
type TypeFilter = "all" | "fact" | "preference" | "episodic";

export default function MemoriesPage() {
  const { connected, demoMode, hydrateFromStorage } = useAppStore();

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  if (!connected && !demoMode) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base p-4">
        <ConnectionPanel />
      </div>
    );
  }

  return <MemoriesShell />;
}

function MemoriesShell() {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);
  const [selectedSpaceTag] = useState(() => {
    if (typeof window === "undefined") return "default";
    return new URLSearchParams(window.location.search).get("space") ?? "default";
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [results, setResults] = useState<SearchMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [filterMode, setFilterMode] = useState<FilterMode>("memory");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [tagFilter, setTagFilter] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "timeline">("grid");
  const [selectedMemory, setSelectedMemory] = useState<SearchMemory | null>(
    null
  );

  const doSearch = useCallback(
    async (q: string) => {
      setSearchQuery(q);
      setLoading(true);
      setHasSearched(true);
      try {
        if (demoMode) {
          const data = getMockSearchResults(q, typeFilter, selectedSpaceTag);
          setResults(data.results);
        } else {
          const searchMode =
            filterMode === "all"
              ? "hybrid"
              : filterMode === "memory"
                ? "memory"
                : "rag";
          const data = await getClient().search(q || "", entityId, {
            searchMode,
            topK: 50,
            filters: selectedSpaceTag !== "default" ? { container_tag: selectedSpaceTag } : undefined,
          });
          let filtered = data.results;
          if (typeFilter !== "all") {
            filtered = filtered.filter((m) => m.memory_type === typeFilter);
          }
          if (tagFilter) {
            filtered = filtered.filter(
              (m) => m.tags?.includes(tagFilter)
            );
          }
          setResults(filtered);
        }
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [entityId, filterMode, typeFilter, tagFilter, demoMode, selectedSpaceTag]
  );

  // Initial load
  useEffect(() => {
    doSearch("");
  }, [doSearch]);

  const filterModes: { key: FilterMode; label: string; icon: typeof Brain }[] =
    [
      { key: "memory", label: "记忆", icon: Brain },
      { key: "rag", label: "RAG", icon: BookOpen },
      { key: "all", label: "全部", icon: ListFilter },
    ];

  const typeFilters: { key: TypeFilter; label: string }[] = [
    { key: "all", label: "全部类型" },
    { key: "fact", label: "事实" },
    { key: "preference", label: "偏好" },
    { key: "episodic", label: "情节" },
  ];

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto">
        <DemoBanner />
        <div className="flex-1 p-6">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight">
              {searchQuery ? `搜索: ${searchQuery}` : "记忆浏览"}
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              {results.length > 0
                ? `找到 ${results.length} 条记忆`
                : "搜索和浏览 Emerald 中存储的记忆"}
            </p>
          </div>

          <div className="mb-4 space-y-3">
            <SearchBar
              onSearch={doSearch}
              loading={loading}
              placeholder="搜索记忆内容…"
              autoSearch
            />

            {/* View toggle + Filter bar */}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-surface-border bg-surface-card p-2">
              <Filter className="ml-1 h-3.5 w-3.5 text-fg-subtle" />
              
              <div className="flex gap-0.5 rounded-md bg-surface-hover p-0.5">
                {filterModes.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => {
                      setFilterMode(f.key);
                      doSearch(searchQuery);
                    }}
                    className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-all ${
                      filterMode === f.key
                        ? "bg-surface-card text-fg-primary shadow-xs"
                        : "text-fg-subtle hover:text-fg-muted"
                    }`}
                  >
                    <f.icon className="h-3 w-3" />
                    {f.label}
                  </button>
                ))}
              </div>

              <div className="h-4 w-px bg-surface-border" />

              <div className="flex gap-1">
                {typeFilters.map((t) => (
                  <button
                    key={t.key}
                    onClick={() => {
                      setTypeFilter(t.key);
                      doSearch(searchQuery);
                    }}
                    className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                      typeFilter === t.key
                        ? "bg-brand-accent-subtle text-brand-accent"
                        : "text-fg-subtle hover:bg-surface-hover"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {/* Tag filter */}
              <input
                value={tagFilter}
                onChange={(e) => {
                  setTagFilter(e.target.value);
                  doSearch(searchQuery);
                }}
                placeholder="Filter by tag…"
                className="w-24 rounded-md bg-surface-hover px-2 py-1 text-xs text-fg-primary placeholder:text-fg-faint border border-surface-border/50 focus:outline-none focus:ring-1 focus:ring-surface-ring"
              />

              {/* View toggle */}
              <div className="flex gap-0.5 rounded-md bg-surface-hover p-0.5">
                <button
                  onClick={() => setViewMode("grid")}
                  className={`flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-all ${
                    viewMode === "grid"
                      ? "bg-surface-card text-fg-primary shadow-xs"
                      : "text-fg-subtle hover:text-fg-muted"
                  }`}
                >
                  <Grid3X3 className="h-3 w-3" />
                  Grid
                </button>
                <button
                  onClick={() => setViewMode("timeline")}
                  className={`flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-all ${
                    viewMode === "timeline"
                      ? "bg-surface-card text-fg-primary shadow-xs"
                      : "text-fg-subtle hover:text-fg-muted"
                  }`}
                >
                  <LayoutList className="h-3 w-3" />
                  Timeline
                </button>
              </div>

              <div className="ml-auto flex items-center gap-1">
                {searchQuery && (
                  <button
                    onClick={() => { doSearch(""); setTagFilter(""); }}
                    className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-surface-hover"
                  >
                    <X className="h-3 w-3" />
                    清除
                  </button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => doSearch(searchQuery)}
                  disabled={loading}
                  className="h-7 px-2"
                >
                  <RotateCcw className="h-3 w-3" />
                </Button>
              </div>
            </div>
          </div>

          {/* Results */}
          {viewMode === "grid" ? (
            <MemoriesGrid
              memories={results}
              onMemoryClick={(m) => setSelectedMemory(m)}
              emptyMessage={
                hasSearched ? "没有匹配的记忆" : "正在加载…"
              }
            />
          ) : (
            <TimelineView
              memories={results}
              onMemoryClick={(m) => setSelectedMemory(m)}
              emptyMessage={
                hasSearched ? "没有匹配的记忆" : "正在加载…"
              }
            />
          )}
        </div>
      </main>

      <MemoryDetailModal
        memory={selectedMemory}
        onClose={() => setSelectedMemory(null)}
      />
    </div>
  );
}
