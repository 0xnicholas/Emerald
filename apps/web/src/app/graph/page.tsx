"use client";

import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { MemoryDetailModal } from "@/components/memories/memory-detail-modal";
import { DemoBanner } from "@/components/layout/demo-banner";
import { SearchBar } from "@/components/search/search-bar";
import { getClient } from "@/lib/api";
import type { SearchMemory } from "@/lib/types";
import { MOCK_MEMORIES, getMockSearchResults } from "@/lib/mock-data";
import { Button } from "@/components/ui/button";
import { RotateCcw, ZoomIn, ZoomOut, Maximize2 } from "lucide-react";

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

function GraphShell() {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);
  const [memories, setMemories] = useState<SearchMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedMemory, setSelectedMemory] = useState<SearchMemory | null>(
    null
  );

  const loadGraph = useCallback(
    async (q: string) => {
      setLoading(true);
      try {
        if (demoMode) {
          const data = getMockSearchResults(q);
          setMemories(data.results);
        } else {
          const data = await getClient().search(q, entityId, {
            searchMode: "memory",
            topK: 80,
          });
          setMemories(data.results);
        }
        setSearchQuery(q);
      } catch {
        setMemories([]);
      } finally {
        setLoading(false);
      }
    },
    [entityId, demoMode]
  );

  useEffect(() => {
    loadGraph("");
  }, [loadGraph]);

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-hidden">
        <DemoBanner />
        {/* Top bar */}
        <div className="flex items-center gap-3 border-b border-zinc-200 p-3 dark:border-zinc-700">
          <div className="flex-1 max-w-md">
            <SearchBar
              onSearch={loadGraph}
              loading={loading}
              placeholder="在图谱中搜索…"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadGraph(searchQuery)}
            disabled={loading}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            刷新
          </Button>
          <span className="text-xs text-zinc-400">
            {memories.length} 个节点
          </span>
        </div>

        {/* Graph canvas */}
        <div className="flex-1 overflow-hidden">
          <KnowledgeGraph
            memories={memories}
            onNodeClick={(m) => setSelectedMemory(m)}
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
