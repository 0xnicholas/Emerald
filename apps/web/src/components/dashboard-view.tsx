"use client";

import { useMemo, useState, useEffect, useCallback } from "react";
import { motion } from "motion/react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { MOCK_PROFILE, MOCK_MEMORIES } from "@/lib/mock-data";
import { useAppStore } from "@/stores/app";
import { useProfile } from "@/hooks/use-profile";
import { useSearchMemories } from "@/hooks/use-search-memories";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Heading, Label } from "@/components/ui/typography";
import { Separator } from "@/components/ui/separator";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";
import { toast } from "sonner";
import { AddMemoryModal } from "@/components/add-memory-modal";
import type { SearchMemory } from "@/lib/types";
import {
  Brain, Search, ArrowRight, Zap, Layers, Network, Bookmark, Activity,
  Star, MessageSquare, FileText, Lightbulb, Sparkles, Clock, Calendar, Plus, Folder,
  Send, Loader, RefreshCw, Quote, Hexagon,
} from "lucide-react";

// ─── Animation ───────────────────────────────────────────────────────

const fadeUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.3, ease: [0.4, 0, 0.2, 1] as [number, number, number, number] },
};

// ─── Glowing card wrapper ────────────────────────────────────────────

function GlassCard({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-[18px] border border-surface-border bg-surface-card/60 shadow-[0_12px_40px_rgba(0,0,0,0.22)] backdrop-blur-md ${className ?? ""}`}
      {...props}
    >
      {children}
    </div>
  );
}

// ─── Stat Card ───────────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, sub, color, delay = 0 }: {
  icon: typeof Brain; label: string; value: string | number; sub: string; color: string; delay?: number;
}) {
  return (
    <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay }}>
      <GlassCard className="p-5">
        <div className={`mb-3 inline-flex rounded-xl p-3 ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <p className="text-2xl font-bold tracking-tight text-fg-primary">{value}</p>
        <p className="mt-0.5 text-sm text-fg-muted">{label}</p>
        <p className="mt-0.5 text-xs text-fg-subtle">{sub}</p>
      </GlassCard>
    </motion.div>
  );
}

// ─── Memory Row ──────────────────────────────────────────────────────

const typeColors: Record<string, string> = {
  fact: "border-l-[#34d399]",
  preference: "border-l-[#a78bfa]",
  episodic: "border-l-[#fbbf24]",
};

const typeIcons: Record<string, typeof FileText> = {
  fact: FileText, preference: Star, episodic: MessageSquare,
};

function MemoryRow({ memory, index }: { memory: SearchMemory; index: number }) {
  const Icon = typeIcons[memory.memory_type] ?? Brain;
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay: index * 0.03 }}
      className={`group flex items-start gap-3 rounded-[18px] border border-surface-border border-l-4 bg-surface-card/60 p-3.5 shadow-[0_12px_40px_rgba(0,0,0,0.22)] backdrop-blur-md transition-all hover:shadow-[0_12px_40px_rgba(0,0,0,0.34)] ${typeColors[memory.memory_type] ?? "border-l-surface-border"}`}
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-relaxed text-fg-primary">{memory.content}</p>
        {memory.summary && <p className="mt-0.5 text-xs text-fg-muted">{memory.summary}</p>}
        <div className="mt-1.5 flex items-center gap-2">
          <Badge className={memoryTypeColor(memory.memory_type)}>
            {memoryTypeLabel(memory.memory_type)}
          </Badge>
          {memory.score !== undefined && <span className="text-xs text-fg-subtle">{Math.round(memory.score * 100)}%</span>}
        </div>
      </div>
    </motion.div>
  );
}

// ─── HighlightsCard ──────────────────────────────────────────────────

function HighlightsCard({ memories }: { memories: SearchMemory[] }) {
  if (!memories.length) return null;
  return (
    <GlassCard className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-brand-accent" />
        <Label level="3" weight="medium" className="text-fg-faint">TODAY'S BRIEF</Label>
      </div>
      <p className="text-sm leading-relaxed text-fg-primary">{memories[0].content}</p>
      {memories.length > 1 && (
        <ul className="mt-2 space-y-1">
          {memories.slice(1, 4).map((mem, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-fg-muted">
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-accent" />
              {mem.summary || mem.content.slice(0, 80)}
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}

// ─── MemoryOfDayCard ─────────────────────────────────────────────────

function MemoryOfDayCard({ memory }: { memory: SearchMemory }) {
  const Icon = typeIcons[memory.memory_type] ?? Brain;
  return (
    <GlassCard className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <Calendar className="h-4 w-4 text-amber-500" />
        <Label level="3" weight="medium" className="text-fg-faint">MEMORY OF THE DAY</Label>
      </div>
      <div className="flex items-start gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <p className="text-xs leading-relaxed text-fg-primary">{memory.content.slice(0, 120)}</p>
          <Badge className={`mt-1.5 ${memoryTypeColor(memory.memory_type)}`}>
            {memoryTypeLabel(memory.memory_type)}
          </Badge>
        </div>
      </div>
    </GlassCard>
  );
}

// ─── StatFactsCard ───────────────────────────────────────────────────

function StatFactsCard() {
  const demoMode = useAppStore((s) => s.demoMode);
  const entityId = useAppStore((s) => s.entityId);
  const profileQuery = useProfile(entityId, { enabled: !demoMode });
  const profile = demoMode ? MOCK_PROFILE : profileQuery.data;
  if (!profile?.static.length) return null;

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <Bookmark className="h-4 w-4 text-brand-accent" />
        <Label level="3" weight="medium" className="text-fg-faint">PROFILE FACTS</Label>
        <Badge className="ml-auto bg-surface-hover text-fg-muted">{profile.static.length}</Badge>
      </div>
      <div className="space-y-1.5">
        {profile.static.map((f, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04 }}
            className="rounded-lg border border-surface-border bg-surface-card/60 p-3 backdrop-blur-md"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm text-fg-primary">{f.content}</p>
              <span className="shrink-0 text-xs text-fg-subtle">{Math.round(f.importance * 100)}%</span>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-hover">
              <div className="h-full rounded-full bg-brand-accent" style={{ width: `${f.importance * 100}%` }} />
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

// ─── Static Graph Preview ───────────────────────────────────────────

function StaticGraphPreview({ entityId, demoMode }: { entityId: string; demoMode: boolean }) {
  const queryClient = useQueryClient();

  const graphQuery = useQuery({
    queryKey: ["graph", entityId],
    queryFn: () => getClient().getGraph(entityId, 30),
    enabled: !!entityId && !demoMode,
    staleTime: 60_000,
  });

  const [hovered, setHovered] = useState(false);

  const nodeCount = demoMode ? 12 : graphQuery.data?.nodes.length ?? 0;
  const edgeCount = demoMode ? 8 : graphQuery.data?.edges.length ?? 0;

  return (
    <Link href="/graph">
      <GlassCard
        className="group relative overflow-hidden p-4 transition-all hover:shadow-[0_12px_40px_rgba(0,0,0,0.34)]"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div className="relative z-10 flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Network className="h-4 w-4 text-brand-accent" />
            <Label level="3" weight="medium" className="text-fg-faint">KNOWLEDGE GRAPH</Label>
          </div>
          <div className="flex items-center gap-2 text-xs text-fg-faint">
            <span>{nodeCount} nodes</span>
            <span className="text-fg-faint/50">·</span>
            <span>{edgeCount} edges</span>
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </div>
        </div>

        {/* Mini graph visualization */}
        <div className="relative h-32 w-full overflow-hidden rounded-xl bg-surface-hover/30">
          {/* Decorative node dots */}
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 400 120">
            {/* Edges */}
            {demoMode
              ? generateDemoEdges(12).map((e, i) => (
                  <line
                    key={`e${i}`}
                    x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
                    stroke="rgb(38, 51, 72)"
                    strokeWidth="0.8"
                    className="transition-all"
                    style={{ opacity: hovered ? 0.8 : 0.5 }}
                  />
                ))
              : null}
            {/* Nodes */}
            {demoMode
              ? generateDemoNodes(12).map((n, i) => (
                  <g key={`n${i}`}>
                    <circle
                      cx={n.x} cy={n.y} r={n.r}
                      fill={n.color}
                      opacity={hovered ? 0.9 : 0.6}
                      className="transition-all"
                    />
                  </g>
                ))
              : null}
          </svg>

          {/* Loading state */}
          {graphQuery.isLoading && !demoMode && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader className="h-5 w-5 animate-spin text-fg-muted" />
            </div>
          )}
        </div>

        <p className="mt-2 text-xs text-fg-muted">
          Click to explore memory connections in the full graph view
        </p>
      </GlassCard>
    </Link>
  );
}

function generateDemoNodes(count: number) {
  const types = ["#34d399", "#a78bfa", "#fbbf24"];
  return Array.from({ length: count }, (_, i) => ({
    x: 30 + Math.random() * 340,
    y: 15 + Math.random() * 90,
    r: 4 + Math.random() * 6,
    color: types[i % 3],
  }));
}

function generateDemoEdges(count: number) {
  const edges = [];
  for (let i = 0; i < count; i++) {
    const nodes = generateDemoNodes(2);
    edges.push({ x1: nodes[0].x, y1: nodes[0].y, x2: nodes[1].x, y2: nodes[1].y });
  }
  return edges;
}

// ─── Tip Rotation ───────────────────────────────────────────────────

const TIPS = [
  { icon: <Sparkles className="h-4 w-4" />, text: "Press ⌘K to quickly search or navigate anywhere" },
  { icon: <MessageSquare className="h-4 w-4" />, text: "Use the Chat panel to ask questions about your memories" },
  { icon: <Network className="h-4 w-4" />, text: "Explore memory connections in the Knowledge Graph" },
  { icon: <Lightbulb className="h-4 w-4" />, text: "Press C to quickly add a new memory from anywhere" },
  { icon: <Search className="h-4 w-4" />, text: "Use hybrid search to find both documents and memories" },
  { icon: <Calendar className="h-4 w-4" />, text: "Memories automatically expire based on temporal relevance" },
  { icon: <Zap className="h-4 w-4" />, text: "Connect external services via the Integrations page" },
  { icon: <Bookmark className="h-4 w-4" />, text: "Profile facts are always injected before any search" },
];

function TipRotationCard() {
  const [index, setIndex] = useState(0);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    const interval = setInterval(() => {
      setFading(true);
      setTimeout(() => {
        setIndex((i) => (i + 1) % TIPS.length);
        setFading(false);
      }, 300);
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  const tip = TIPS[index];

  return (
    <GlassCard className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <Quote className="h-4 w-4 text-amber-500" />
        <Label level="3" weight="medium" className="text-fg-faint">TIP OF THE DAY</Label>
        <button
          onClick={() => { setIndex((i) => (i + 1) % TIPS.length); }}
          className="ml-auto rounded-md p-1 text-fg-faint hover:bg-surface-hover hover:text-fg-muted transition-colors"
          title="Next tip"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>
      <div
        className={`flex items-start gap-3 transition-opacity duration-300 ${
          fading ? "opacity-30" : "opacity-100"
        }`}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-accent-subtle text-brand-accent">
          {tip.icon}
        </div>
        <p className="text-sm leading-relaxed text-fg-primary">{tip.text}</p>
      </div>
      {/* Dots */}
      <div className="mt-3 flex items-center gap-1.5">
        {TIPS.map((_, i) => (
          <button
            key={i}
            onClick={() => setIndex(i)}
            className={`h-1.5 rounded-full transition-all ${
              i === index
                ? "w-4 bg-brand-accent"
                : "w-1.5 bg-surface-border hover:bg-fg-faint"
            }`}
          />
        ))}
      </div>
    </GlassCard>
  );
}

// ─── Main Dashboard View ─────────────────────────────────────────────

export function DashboardView({ entityId }: { entityId: string }) {
  const demoMode = useAppStore((s) => s.demoMode);
  const [addOpen, setAddOpen] = useState(false);
  const [quickNote, setQuickNote] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const queryClient = useQueryClient();

  const handleQuickSave = useCallback(async () => {
    if (!quickNote.trim() || savingNote) return;
    setSavingNote(true);
    try {
      if (demoMode) {
        // In demo mode, just clear the input
        setQuickNote("");
        return;
      }
      await getClient().addMemory(quickNote.trim(), entityId, { contentType: "text" });
      setQuickNote("");
      toast.success("Note saved!");
      queryClient.invalidateQueries({ queryKey: ["search-demo", entityId] });
    } catch {
      toast.error("Failed to save note");
    } finally {
      setSavingNote(false);
    }
  }, [quickNote, entityId, demoMode, savingNote, queryClient]);

  // Use URL-based space selection (client-side safe, no Suspense needed)
  const [selectedSpaceTag, setSelectedSpaceTag] = useState(() => {
    if (typeof window === "undefined") return "default";
    return new URLSearchParams(window.location.search).get("space") ?? "default";
  });

  // Read ?add=note from URL (set by CommandPalette)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("add") === "note") {
      setAddOpen(true);
      // Clean the URL
      const url = new URL(window.location.href);
      url.searchParams.delete("add");
      window.history.replaceState(null, "", url.toString());
    }
  }, []);

  const profileQuery = useProfile(entityId, { enabled: !demoMode });
  const searchQuery = useSearchMemories("", entityId, {
    searchMode: "memory",
    topK: 8,
    filters: selectedSpaceTag !== "default" ? { container_tag: selectedSpaceTag } : undefined,
  });

  const profile = demoMode ? MOCK_PROFILE : profileQuery.data;
  const memories = demoMode ? MOCK_MEMORIES.slice(0, 8) : (searchQuery.data?.results ?? []);
  const isLoading = !demoMode && (profileQuery.isLoading || searchQuery.isLoading);

  const stats = useMemo(() => [
    { icon: Brain, label: "Total Memories", value: profile?.memory_count ?? 0, sub: "Facts · Preferences · Episodic", color: "bg-bg-info text-text-info" },
    { icon: Bookmark, label: "Static Facts", value: profile?.static.length ?? 0, sub: "Always relevant information", color: "bg-bg-success text-text-success" },
    { icon: Activity, label: "Dynamic Context", value: profile?.dynamic.length ?? 0, sub: "Recent activity & status", color: "bg-bg-warning text-text-warning" },
    { icon: Layers, label: "Memory Types", value: "3 Types", sub: "Fact · Preference · Episodic", color: "bg-bg-info text-text-info" },
  ], [profile]);

  const memoryOfDay = memories[0] ?? null;

  const StatSkeleton = ({ delay = 0 }) => (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay }}>
      <GlassCard className="p-5">
        <Skeleton className="mb-4 h-11 w-11 rounded-xl" />
        <Skeleton className="mb-1 h-7 w-20" />
        <Skeleton className="mb-0.5 h-4 w-32" />
        <Skeleton className="h-3 w-24" />
      </GlassCard>
    </motion.div>
  );

  const MemSkeleton = ({ delay = 0 }: { delay?: number }) => (
    <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2, delay }}>
      <div className="flex items-start gap-3 rounded-[18px] border border-surface-border bg-surface-card/60 p-3.5">
        <Skeleton className="mt-0.5 h-8 w-8 shrink-0 rounded-lg" />
        <div className="min-w-0 flex-1 space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-5 w-14 rounded-full" />
        </div>
      </div>
    </motion.div>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0 }}>
        <div className="flex items-end justify-between gap-4 border-b border-surface-border pb-4">
          <div>
            <Label level="3" weight="medium" className="text-fg-faint">HOME</Label>
            <Heading level="h1" weight="bold" className="mt-1 max-w-2xl text-lg md:text-2xl">
              {demoMode ? "Emerald Demo" : `Welcome back, ${entityId}`}
            </Heading>
          </div>
          <div className="flex items-center gap-2 text-xs text-fg-subtle shrink-0">
            <Clock className="h-3 w-3" />
            {new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric" })}
          </div>
        </div>
      </motion.div>

      {/* Quick Note */}
      <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.03 }}>
        <div className="rounded-[18px] border border-surface-border bg-surface-card/60 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="h-4 w-4 text-brand-accent" />
            <span className="text-xs font-medium text-fg-faint">QUICK NOTE</span>
          </div>
          <div className="flex gap-2">
            <textarea
              value={quickNote}
              onChange={(e) => setQuickNote(e.target.value)}
              placeholder="Write a quick note..."
              rows={2}
              className="flex-1 rounded-xl border border-surface-border bg-surface-hover/50 px-3 py-2 text-sm text-fg-primary placeholder:text-fg-faint focus:outline-none focus:ring-2 focus:ring-surface-ring resize-none"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleQuickSave();
                }
              }}
            />
            <button
              onClick={handleQuickSave}
              disabled={!quickNote.trim() || savingNote}
              className="self-end flex items-center gap-1.5 rounded-xl bg-brand-accent px-3 py-2 text-xs font-medium text-white hover:bg-brand-accent/90 transition-colors disabled:opacity-40"
            >
              {savingNote ? (
                <Loader className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              Save
            </button>
          </div>
          <p className="mt-1.5 text-[10px] text-fg-faint">⌘+Enter to save</p>
        </div>
      </motion.div>

      {/* Stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => <StatSkeleton key={i} delay={i * 0.05} />)
          : stats.map((s, i) => <StatCard key={s.label} {...s} delay={i * 0.05} />)}
      </div>

      {/* Daily Brief */}
      <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.05 }}>
        <div className="flex flex-col gap-3 lg:flex-row">
          <div className="flex-[3] min-w-0">
            {isLoading ? (
              <GlassCard className="p-4">
                <Skeleton className="mb-2 h-4 w-24" />
                <Skeleton lines={2} className="h-3" />
              </GlassCard>
            ) : <HighlightsCard memories={memories} />}
          </div>
          <div className="flex-[2] min-w-0">
            {isLoading ? (
              <GlassCard className="p-4">
                <Skeleton className="mb-2 h-4 w-20" />
                <Skeleton className="h-3 w-full" />
              </GlassCard>
            ) : memoryOfDay ? (
              <MemoryOfDayCard memory={memoryOfDay} />
            ) : (
              <GlassCard className="flex items-center justify-center p-4 text-xs text-fg-subtle">
                No memories yet
              </GlassCard>
            )}
          </div>
        </div>
      </motion.div>

      {/* Quick Actions */}
      <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.1 }}>
        <Card>
          <CardContent className="flex flex-wrap items-center gap-1 p-3">
            <Link href="/memories"><Button variant="ghost" size="sm"><Search className="h-4 w-4" /> Search</Button></Link>
            <Separator orientation="vertical" className="h-5" />
            <Button variant="ghost" size="sm" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /> Add</Button>
            <Separator orientation="vertical" className="h-5" />
            <Link href="/graph"><Button variant="ghost" size="sm"><Network className="h-4 w-4" /> Graph</Button></Link>
            <Separator orientation="vertical" className="h-5" />
            <Link href="/integrations"><Button variant="ghost" size="sm"><Hexagon className="h-4 w-4" /> Integrations</Button></Link>
            <Separator orientation="vertical" className="h-5" />
            <Link href="/settings"><Button variant="ghost" size="sm"><Zap className="h-4 w-4" /> API</Button></Link>
            <div className="ml-auto hidden items-center gap-1.5 text-xs text-fg-subtle md:flex">
              <Lightbulb className="h-3 w-3 text-amber-500" />
              <span>Click a memory card to view details</span>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Graph Preview + Tip */}
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.12 }}>
            <StaticGraphPreview entityId={entityId} demoMode={demoMode} />
          </motion.div>
        </div>
        <div className="lg:col-span-2">
          <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.14 }}>
            <TipRotationCard />
          </motion.div>
        </div>
      </div>

      {/* Recent + Profile */}
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.15 }}>
            <div className="mb-3 flex items-center justify-between">
              <Label level="3" weight="medium" className="text-fg-faint">RECENTLY SAVED</Label>
              <Link href="/memories" className="flex items-center gap-1 text-xs text-brand-accent hover:underline">
                View all <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            <div className="space-y-1.5">
              {isLoading
                ? Array.from({ length: 3 }).map((_, i) => <MemSkeleton key={i} delay={i * 0.05} />)
                : memories.length > 0
                  ? memories.map((mem, i) => <MemoryRow key={mem.id} memory={mem} index={i} />)
                  : <div className="flex flex-col items-center justify-center py-12 text-fg-subtle">
                      <Brain className="mb-2 h-8 w-8 opacity-40" />
                      <p className="text-sm">No memories yet</p>
                    </div>}
            </div>
          </motion.div>
        </div>
        <div className="lg:col-span-2">
          <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.2 }}>
            <StatFactsCard />
          </motion.div>
        </div>
      </div>
      <AddMemoryModal isOpen={addOpen} onClose={() => setAddOpen(false)} />
      <div className="h-8" />
    </div>
  );
}
