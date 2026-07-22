"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { MobileBottomNav } from "@/components/layout/mobile-bottom-nav";
import { AddMemoryModal } from "@/components/add-memory-modal";
import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { MemoryDetailModal } from "@/components/memories/memory-detail-modal";
import { DemoBanner } from "@/components/layout/demo-banner";
import { SearchBar } from "@/components/search/search-bar";
import { getClient } from "@/lib/api";
import type { GraphNode, GraphEdge } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/typography";
import { Separator } from "@/components/ui/separator";
import {
  RotateCcw, ZoomIn, ZoomOut, Minus, Plus, X,
  FileText, Star, MessageSquare, Brain, Search,
  Filter, Eye, EyeOff, Info,
} from "lucide-react";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";

export default function GraphPage() {
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

  return <GraphShell />;
}

function GraphShell() {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);
  const [addOpen, setAddOpen] = useState(false);
  const [selectedSpaceTag] = useState(() => {
    if (typeof window === "undefined") return "default";
    return new URLSearchParams(window.location.search).get("space") ?? "default";
  });

  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [zoomLevel, setZoomLevel] = useState(1);
  const [showTypes, setShowTypes] = useState<Record<string, boolean>>({ fact: true, preference: true, episodic: true });
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      if (demoMode) {
        // Generate mock graph data from memories
        const { MOCK_MEMORIES, MOCK_SPACES } = await import("@/lib/mock-data");
        const mems = MOCK_MEMORIES.filter(
          (m) => selectedSpaceTag === "default" || m.container_tag === selectedSpaceTag
        );
        const nodes: GraphNode[] = mems.map((m) => ({
          id: m.id,
          label: m.summary || m.content.slice(0, 60),
          type: m.memory_type,
          confidence: m.score ?? 0.5,
        }));
        const edges: GraphEdge[] = [];
        for (let i = 0; i < nodes.length - 1; i++) {
          if (nodes[i].type === nodes[i + 1].type) {
            edges.push({ source: nodes[i].id, target: nodes[i + 1].id, type: "EXTENDS" });
          }
        }
        setGraphData({ nodes, edges });
      } else {
        const data = await getClient().getGraph(entityId, 150);
        setGraphData(data);
      }
    } catch {
      setGraphData({ nodes: [], edges: [] });
    } finally {
      setLoading(false);
    }
  }, [entityId, demoMode, selectedSpaceTag]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  const selectedTypes = useMemo(
    () => Object.entries(showTypes).filter(([, v]) => v).map(([k]) => k),
    [showTypes]
  );

  const toggleType = useCallback((type: string) => {
    setShowTypes((prev) => ({ ...prev, [type]: !prev[type] }));
  }, []);

  const handleNodeClick = useCallback((nodeId: string) => {
    const node = graphData.nodes.find((n) => n.id === nodeId);
    if (node) setSelectedNode(node);
  }, [graphData.nodes]);

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of graphData.nodes) {
      counts[n.type] = (counts[n.type] ?? 0) + 1;
    }
    return counts;
  }, [graphData.nodes]);

  const edgeTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of graphData.edges) {
      counts[e.type] = (counts[e.type] ?? 0) + 1;
    }
    return counts;
  }, [graphData.edges]);

  if (loading && graphData.nodes.length === 0) {
    return (
      <LoadingShell>
        <div className="flex items-center justify-center flex-1">
          <p className="text-sm text-fg-muted animate-pulse">Loading graph...</p>
        </div>
      </LoadingShell>
    );
  }

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-hidden">
        <DemoBanner />

        {/* Top bar */}
        <div className="flex items-center gap-3 border-b border-surface-border px-4 py-2.5">
          {/* Search in graph */}
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-fg-muted" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search in graph..."
              className="w-full rounded-lg bg-surface-hover border border-surface-border/50 pl-8 pr-3 py-1.5 text-xs text-fg-primary placeholder:text-fg-faint focus:outline-none focus:ring-1 focus:ring-surface-ring"
            />
          </div>

          {/* Type filters */}
          <div className="flex items-center gap-1.5">
            <Filter className="h-3.5 w-3.5 text-fg-faint" />
            {["fact", "preference", "episodic"].map((type) => (
              <button
                key={type}
                onClick={() => toggleType(type)}
                className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all ${
                  showTypes[type]
                    ? memoryTypeColor(type) + " ring-1 ring-surface-ring/30"
                    : "bg-surface-hover text-fg-faint opacity-50"
                }`}
              >
                {showTypes[type] ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                {memoryTypeLabel(type)}
                <span className="text-[10px] opacity-70">({typeCounts[type] ?? 0})</span>
              </button>
            ))}
          </div>

          {/* Zoom */}
          <div className="flex items-center gap-0.5 rounded-lg border border-surface-border p-0.5">
            <button onClick={() => setZoomLevel((z) => Math.max(0.3, z - 0.2))} className="rounded-md p-1 text-fg-muted hover:bg-surface-hover" title="Zoom out">
              <Minus className="h-3.5 w-3.5" />
            </button>
            <span className="w-10 text-center text-[11px] font-medium text-fg-muted tabular-nums">
              {Math.round(zoomLevel * 100)}%
            </span>
            <button onClick={() => setZoomLevel((z) => Math.min(3, z + 0.2))} className="rounded-md p-1 text-fg-muted hover:bg-surface-hover" title="Zoom in">
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* Stats */}
          <span className="text-[11px] text-fg-faint tabular-nums">
            {graphData.nodes.length} nodes · {graphData.edges.length} edges
          </span>

          <Button variant="ghost" size="sm" onClick={loadGraph} disabled={loading} className="h-7 w-7 p-0">
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Main area */}
        <div className="flex flex-1 overflow-hidden">
          {/* Graph */}
          <div className="flex-1 overflow-hidden relative">
            {loading && (
              <div className="absolute top-3 right-3 z-10 flex items-center gap-2 rounded-lg bg-surface-card/80 px-3 py-1.5 text-xs text-fg-muted backdrop-blur-sm border border-surface-border/50">
                <div className="h-3 w-3 rounded-full border-2 border-brand-accent border-t-transparent animate-spin" />
                Updating...
              </div>
            )}
            <KnowledgeGraph
              nodes={graphData.nodes}
              edges={graphData.edges}
              onNodeClick={handleNodeClick}
              zoomLevel={zoomLevel}
              selectedTypes={selectedTypes}
              searchQuery={searchQuery}
            />
          </div>

          {/* Side panel */}
          {selectedNode && (
            <div className="w-72 shrink-0 border-l border-surface-border overflow-y-auto bg-surface-base/80">
              <div className="flex items-center justify-between border-b border-surface-border/50 px-4 py-3">
                <h3 className="text-xs font-semibold text-fg-primary">Node Details</h3>
                <button onClick={() => setSelectedNode(null)} className="rounded p-1 text-fg-muted hover:bg-surface-hover">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="p-4 space-y-4">
                <div className="flex items-center gap-2">
                  <Badge className={memoryTypeColor(selectedNode.type)}>
                    {memoryTypeLabel(selectedNode.type)}
                  </Badge>
                  <span className="text-xs text-fg-faint">{Math.round(selectedNode.confidence * 100)}%</span>
                </div>
                <p className="text-sm leading-relaxed text-fg-primary">{selectedNode.label}</p>
                <Separator />
                <Label level="3" weight="medium" className="text-fg-faint">CONNECTIONS</Label>
                <div className="space-y-1 text-xs">
                  {graphData.edges.filter((e) => e.source === selectedNode.id || e.target === selectedNode.id).length > 0 ? (
                    graphData.edges
                      .filter((e) => e.source === selectedNode.id || e.target === selectedNode.id)
                      .slice(0, 10)
                      .map((e, i) => {
                        const otherId = e.source === selectedNode.id ? e.target : e.source;
                        const other = graphData.nodes.find((n) => n.id === otherId);
                        return (
                          <div key={i} className="rounded-lg bg-surface-hover/50 p-2">
                            <span className="text-[10px] font-medium text-fg-faint uppercase">{e.type.toLowerCase()}</span>
                            <p className="text-xs text-fg-muted truncate">{other?.label ?? otherId}</p>
                          </div>
                        );
                      })
                  ) : (
                    <p className="text-fg-subtle">No direct connections</p>
                  )}
                </div>
                <Separator />
                <p className="text-[10px] font-mono text-fg-faint break-all">ID: {selectedNode.id}</p>
              </div>
            </div>
          )}
        </div>
      </main>
      <MobileBottomNav onAddMemory={() => setAddOpen(true)} />
      <AddMemoryModal isOpen={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}

function LoadingShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col pb-16 md:pb-0">
        <DemoBanner />
        {children}
      </main>
      <MobileBottomNav />
    </div>
  );
}
