"use client";

import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { SearchBar } from "@/components/search/search-bar";
import { MemoriesGrid } from "@/components/memories/memories-grid";
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
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 p-4 dark:bg-zinc-950">
        <ConnectionPanel />
      </div>
    );
  }

  return <MemoriesShell />;
}

function MemoriesShell() {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);
  const [searchQuery, setSearchQuery] = useState("");
  const [results, setResults] = useState<SearchMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [filterMode, setFilterMode] = useState<FilterMode>("memory");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
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
          const data = getMockSearchResults(q, typeFilter);
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
          });
          let filtered = data.results;
          if (typeFilter !== "all") {
            filtered = filtered.filter((m) => m.memory_type === typeFilter);
          }
          setResults(filtered);
        }
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [entityId, filterMode, typeFilter, demoMode]
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
          {/* Search header */}
          <div className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight">记忆浏览</h1>
            <p className="mt-1 text-sm text-zinc-500">
              搜索和浏览 Emerald 中存储的记忆
            </p>
          </div>

          <div className="mb-4 space-y-3">
            <SearchBar
              onSearch={doSearch}
              loading={loading}
              placeholder="搜索记忆内容…"
            />

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex gap-1 rounded-lg border border-zinc-200 p-1 dark:border-zinc-700">
                {filterModes.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => {
                      setFilterMode(f.key);
                      doSearch(searchQuery);
                    }}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                      filterMode === f.key
                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                        : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    }`}
                  >
                    <f.icon className="h-3.5 w-3.5" />
                    {f.label}
                  </button>
                ))}
              </div>

              <select
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value as TypeFilter);
                  doSearch(searchQuery);
                }}
                className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400"
              >
                {typeFilters.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </select>

              <Button
                variant="ghost"
                size="sm"
                onClick={() => doSearch("")}
                disabled={loading}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                刷新
              </Button>

              {results.length > 0 && (
                <span className="text-xs text-zinc-400">
                  {results.length} 条结果
                </span>
              )}
            </div>
          </div>

          {/* Results */}
          <MemoriesGrid
            memories={results}
            onMemoryClick={(m) => setSelectedMemory(m)}
            emptyMessage={
              hasSearched ? "没有匹配的记忆" : "正在加载…"
            }
          />
        </div>
      </main>

      <MemoryDetailModal
        memory={selectedMemory}
        onClose={() => setSelectedMemory(null)}
      />
    </div>
  );
}
