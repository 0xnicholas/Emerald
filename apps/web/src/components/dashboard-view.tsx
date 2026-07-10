"use client";

import { useMemo, useState } from "react";
import { motion } from "motion/react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { MOCK_PROFILE, MOCK_MEMORIES } from "@/lib/mock-data";
import { useAppStore } from "@/stores/app";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Heading, Label } from "@/components/ui/typography";
import { Separator } from "@/components/ui/separator";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";
import { AddMemoryModal } from "@/components/add-memory-modal";
import type { SearchMemory } from "@/lib/types";
import {
  Brain, Search, ArrowRight, Zap, Layers, Network, Bookmark, Activity,
  Star, MessageSquare, FileText, Lightbulb, Sparkles, Clock, Calendar, Plus,
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
  const profileQuery = useQuery({
    queryKey: ["profile", entityId],
    queryFn: () => getClient().getProfile(entityId),
    enabled: !!entityId && !demoMode,
  });
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

// ─── Main Dashboard View ─────────────────────────────────────────────

export function DashboardView({ entityId }: { entityId: string }) {
  const demoMode = useAppStore((s) => s.demoMode);
  const [addOpen, setAddOpen] = useState(false);

  const profileQuery = useQuery({
    queryKey: ["profile", entityId],
    queryFn: () => getClient().getProfile(entityId),
    enabled: !!entityId && !demoMode,
  });
  const searchQuery = useQuery({
    queryKey: ["search-demo", entityId],
    queryFn: () => getClient().search("", entityId, { searchMode: "memory", topK: 8 }),
    enabled: !!entityId && !demoMode,
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
            <Link href="/settings"><Button variant="ghost" size="sm"><Zap className="h-4 w-4" /> API</Button></Link>
            <div className="ml-auto hidden items-center gap-1.5 text-xs text-fg-subtle md:flex">
              <Lightbulb className="h-3 w-3 text-amber-500" />
              <span>Click a memory card to view details</span>
            </div>
          </CardContent>
        </Card>
      </motion.div>

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
