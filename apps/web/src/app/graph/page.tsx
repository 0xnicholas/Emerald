"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { MemoryDetailModal } from "@/components/memories/memory-detail-modal";
import { DemoBanner } from "@/components/layout/demo-banner";
import { SearchBar } from "@/components/search/search-bar";
import { getClient } from "@/lib/api";
import type { SearchMemory } from "@/lib/types";
import { getMockSearchResults } from "@/lib/mock-data";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  RotateCcw,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minus,
  Plus,
  X,
  FileText,
  Star,
  MessageSquare,
  Brain,
} from "lucide-react";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";

export default function GraphPage() {
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

  return <GraphShell />;
}

const typeIcons: Record<string, typeof FileText> = {
  fact: FileText,
  preference: Star,
  episodic: MessageSquare,
};

function GraphShell() {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);
  const [selectedSpaceTag] = useState(() => {
    if (typeof window === "undefined") return "default";
    return new URLSearchParams(window.location.search).get("space") ?? "default";
  });
  const [memories, setMemories] = useState<SearchMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedMemory, setSelectedMemory] = useState<SearchMemory | null>(
    null
  );
  const [showDetail, setShowDetail] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const graphKey = useRef(0);

  const loadGraph = useCallback(
    async (q: string) => {
      setLoading(true);
      try {
        if (demoMode) {
          const data = getMockSearchResults(q, undefined, selectedSpaceTag);
          setMemories(data.results);
        } else {
          const data = await getClient().search(q, entityId, {
            searchMode: "memory",
            topK: 80,
            filters: selectedSpaceTag !== "default" ? { container_tag: selectedSpaceTag } : undefined,
          });
          setMemories(data.results);
        }
        setSearchQuery(q);
        setSelectedMemory(null);
        setShowDetail(false);
        graphKey.current++;
      } catch {
        setMemories([]);
      } finally {
        setLoading(false);
      }
    },
    [entityId, demoMode, selectedSpaceTag]
  );

  useEffect(() => {
    loadGraph("");
  }, [loadGraph]);

  const handleNodeClick = useCallback((mem: SearchMemory) => {
    setSelectedMemory(mem);
    setShowDetail(true);
  }, []);

  const typeCounts = {
    fact: memories.filter((m) => m.memory_type === "fact").length,
    preference: memories.filter((m) => m.memory_type === "preference").length,
    episodic: memories.filter((m) => m.memory_type === "episodic").length,
  };

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-hidden">
        <DemoBanner />

        {/* Top bar */}
        <div className="flex items-center gap-3 border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700">
          <div className="flex-1 max-w-md">
            <SearchBar
              onSearch={loadGraph}
              loading={loading}
              placeholder="在图谱中搜索…"
            />
          </div>

          {/* Zoom controls */}
          <div className="hidden items-center gap-0.5 rounded-lg border border-zinc-200 p-0.5 md:flex dark:border-zinc-700">
            <button
              onClick={() => setZoomLevel((z) => Math.max(0.3, z - 0.2))}
              className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              title="缩小"
            >
              <Minus className="h-4 w-4" />
            </button>
            <span className="w-10 text-center text-xs font-medium text-zinc-500">
              {Math.round(zoomLevel * 100)}%
            </span>
            <button
              onClick={() => setZoomLevel((z) => Math.min(3, z + 0.2))}
              className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              title="放大"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>

          {/* Nodes count */}
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <span className="hidden md:inline">
              共 {memories.length} 个节点
            </span>
            {typeCounts.fact > 0 && (
              <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                📌 {typeCounts.fact}
              </Badge>
            )}
            {typeCounts.preference > 0 && (
              <Badge className="bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                ❤️ {typeCounts.preference}
              </Badge>
            )}
            {typeCounts.episodic > 0 && (
              <Badge className="bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                💭 {typeCounts.episodic}
              </Badge>
            )}
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => loadGraph(searchQuery)}
            disabled={loading}
            className="h-8 w-8 p-0"
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
        </div>

        {/* Main area */}
        <div className="flex flex-1 overflow-hidden">
          {/* Graph */}
          <div className="flex-1 overflow-hidden">
            <KnowledgeGraph
              key={graphKey.current}
              memories={memories}
              onNodeClick={handleNodeClick}
              zoomLevel={zoomLevel}
            />
          </div>

          {/* Side panel: node details */}
          {showDetail && selectedMemory && (
            <div className="w-80 shrink-0 border-l border-zinc-200 overflow-y-auto bg-white dark:border-zinc-700 dark:bg-zinc-900">
              <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
                <h3 className="text-sm font-semibold">节点详情</h3>
                <button
                  onClick={() => setShowDetail(false)}
                  className="rounded p-1 text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-4 p-4">
                {/* Type badge */}
                <div className="flex items-center gap-2">
                  {(() => {
                    const Icon =
                      typeIcons[selectedMemory.memory_type] ?? Brain;
                    return (
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-100 dark:bg-zinc-800">
                        <Icon className="h-4 w-4" />
                      </div>
                    );
                  })()}
                  <Badge
                    className={memoryTypeColor(selectedMemory.memory_type)}
                  >
                    {memoryTypeLabel(selectedMemory.memory_type)}
                  </Badge>
                  {selectedMemory.score !== undefined && (
                    <span className="text-xs font-medium text-zinc-400">
                      {Math.round(selectedMemory.score * 100)}%
                    </span>
                  )}
                </div>

                {/* Content */}
                <div>
                  <label className="mb-1 text-xs font-medium text-zinc-500">
                    内容
                  </label>
                  <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
                    {selectedMemory.content}
                  </p>
                </div>

                {/* Summary */}
                {selectedMemory.summary && (
                  <div>
                    <label className="mb-1 text-xs font-medium text-zinc-500">
                      摘要
                    </label>
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">
                      {selectedMemory.summary}
                    </p>
                  </div>
                )}

                {/* Meta */}
                <div className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-800/50">
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span className="text-zinc-400">来源</span>
                      <p className="font-medium text-zinc-700 dark:text-zinc-300">
                        {selectedMemory.source === "rag" ? "RAG" : "记忆"}
                      </p>
                    </div>
                    <div>
                      <span className="text-zinc-400">状态</span>
                      <p className="font-medium text-zinc-700 dark:text-zinc-300">
                        {selectedMemory.is_latest ? "最新" : "历史"}
                      </p>
                    </div>
                    {selectedMemory.document_title && (
                      <div className="col-span-2">
                        <span className="text-zinc-400">文档</span>
                        <p className="font-medium text-zinc-700 dark:text-zinc-300">
                          {selectedMemory.document_title}
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {/* ID */}
                <p className="text-[10px] text-zinc-400">
                  ID: {selectedMemory.id}
                </p>

                {/* View full detail button */}
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => setSelectedMemory(selectedMemory)}
                >
                  查看完整详情
                </Button>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Full detail modal */}
      {showDetail && (
        <MemoryDetailModal
          memory={selectedMemory}
          onClose={() => setSelectedMemory(null)}
        />
      )}
    </div>
  );
}
