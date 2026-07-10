"use client";

import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { MOCK_PROFILE, MOCK_MEMORIES } from "@/lib/mock-data";
import { useAppStore } from "@/stores/app";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Heading, Label, Title } from "@/components/ui/typography";
import { Separator } from "@/components/ui/separator";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";
import type { SearchMemory } from "@/lib/types";
import {
  Brain,
  Search,
  ArrowRight,
  TrendingUp,
  Zap,
  Layers,
  Network,
  Bookmark,
  Activity,
  Star,
  MessageSquare,
  FileText,
  Link2,
  Lightbulb,
  RotateCcw,
  Sparkles,
  Clock,
  BarChart3,
} from "lucide-react";

// ─── Fade-up animation preset ────────────────────────────────────────

const fadeUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.3, ease: [0.4, 0, 0.2, 1] as [number, number, number, number] },
};

// ─── Types ───────────────────────────────────────────────────────────

interface Stat {
  icon: typeof Brain;
  label: string;
  value: string | number;
  sub: string;
  color: string;
}

// ─── Stat Card ───────────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, sub, color }: Stat) {
  return (
    <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0 }}>
      <div className="rounded-xl border border-surface-border bg-surface-card p-5 transition-all hover:shadow-sm">
        <div className={`mb-3 inline-flex rounded-xl p-3 ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <p className="text-2xl font-bold tracking-tight text-fg-primary">{value}</p>
        <p className="mt-0.5 text-sm text-fg-muted">{label}</p>
        <p className="mt-0.5 text-xs text-fg-subtle">{sub}</p>
      </div>
    </motion.div>
  );
}

// ─── Stat Card Skeleton ──────────────────────────────────────────────

function StatCardSkeleton({ delay = 0 }: { delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
    >
      <div className="rounded-xl border border-surface-border bg-surface-card p-5">
        <Skeleton className="mb-4 h-11 w-11 rounded-xl" />
        <Skeleton className="mb-1 h-7 w-20" />
        <Skeleton className="mb-0.5 h-4 w-32" />
        <Skeleton className="h-3 w-24" />
      </div>
    </motion.div>
  );
}

// ─── Memory Row ──────────────────────────────────────────────────────

function MemoryRow({ memory, index }: { memory: SearchMemory; index: number }) {
  const typeColors: Record<string, string> = {
    fact: "border-l-memory-fact",
    preference: "border-l-memory-preference",
    episodic: "border-l-memory-episodic",
  };
  const icons: Record<string, typeof FileText> = {
    fact: FileText,
    preference: Star,
    episodic: MessageSquare,
  };
  const Icon = icons[memory.memory_type] ?? FileText;

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay: index * 0.03 }}
      className={`group flex items-start gap-3 rounded-xl border border-surface-border border-l-4 bg-surface-card p-3.5 transition-all hover:shadow-sm ${
        typeColors[memory.memory_type] ?? "border-l-surface-border"
      }`}
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-relaxed text-fg-primary">{memory.content}</p>
        {memory.summary && (
          <p className="mt-0.5 text-xs text-fg-muted">{memory.summary}</p>
        )}
        <div className="mt-1.5 flex items-center gap-2">
          <Badge className={memoryTypeColor(memory.memory_type)}>
            {memoryTypeLabel(memory.memory_type)}
          </Badge>
          {memory.score !== undefined && (
            <span className="text-xs text-fg-subtle">
              {Math.round(memory.score * 100)}%
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ─── Memory Row Skeleton ─────────────────────────────────────────────

function MemoryRowSkeleton({ delay = 0 }: { delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay }}
    >
      <div className="flex items-start gap-3 rounded-xl border border-surface-border bg-surface-card p-3.5">
        <Skeleton className="mt-0.5 h-8 w-8 shrink-0 rounded-lg" />
        <div className="min-w-0 flex-1 space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-3 w-3/4" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-14 rounded-full" />
            <Skeleton className="h-4 w-10" />
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── HighlightsCard ──────────────────────────────────────────────────

function HighlightsCard({ memories }: { memories: SearchMemory[] }) {
  if (memories.length === 0) return null;

  return (
    <div className="rounded-xl border border-surface-border bg-gradient-to-br from-surface-card to-surface-hover p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-brand-accent" />
        <Label level="3" weight="medium">今日简报</Label>
      </div>
      <div className="space-y-2">
        <p className="text-sm leading-relaxed text-fg-primary">
          {memories[0].content}
        </p>
        {memories.length > 1 && (
          <ul className="space-y-1">
            {memories.slice(1, 4).map((mem, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-fg-muted">
                <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-brand-accent" />
                {mem.summary || mem.content.slice(0, 80)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ─── MemoryOfDayCard ─────────────────────────────────────────────────

function MemoryOfDayCard({ memory }: { memory: SearchMemory }) {
  const icons: Record<string, typeof Star> = {
    fact: FileText,
    preference: Star,
    episodic: MessageSquare,
  };
  const Icon = icons[memory.memory_type] ?? Brain;

  return (
    <div className="rounded-xl border border-surface-border bg-gradient-to-br from-surface-card to-surface-hover p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <Calendar className="h-4 w-4 text-amber-500" />
        <Label level="3" weight="medium">记忆回顾</Label>
      </div>
      <div className="flex items-start gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-hover text-fg-muted">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <p className="text-xs leading-relaxed text-fg-primary">
            {memory.content.slice(0, 120)}
          </p>
          <Badge className={`mt-1.5 ${memoryTypeColor(memory.memory_type)}`}>
            {memoryTypeLabel(memory.memory_type)}
          </Badge>
        </div>
      </div>
    </div>
  );
}

// ─── Import Calendar icon ────────────────────────────────────────────

import { Calendar } from "lucide-react";

// ─── Stat Facts Card ─────────────────────────────────────────────────

function StatFactsCard() {
  const demoMode = useAppStore((s) => s.demoMode);
  const entityId = useAppStore((s) => s.entityId);

  const profileQuery = useQuery({
    queryKey: ["profile", entityId],
    queryFn: () => getClient().getProfile(entityId),
    enabled: !!entityId && !demoMode,
  });
  const profile = demoMode ? MOCK_PROFILE : profileQuery.data;
  if (!profile || profile.static.length === 0) return null;

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <Bookmark className="h-4 w-4 text-brand-accent" />
        <Label level="3" weight="medium">画像事实</Label>
        <Badge className="ml-auto bg-surface-hover text-fg-muted">
          {profile.static.length}
        </Badge>
      </div>
      <div className="space-y-1.5">
        {profile.static.map((f, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04 }}
            className="rounded-lg border border-surface-border bg-surface-card p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm text-fg-primary">{f.content}</p>
              <span className="shrink-0 text-xs text-fg-subtle">
                {Math.round(f.importance * 100)}%
              </span>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-hover">
              <div
                className="h-full rounded-full bg-brand-accent"
                style={{ width: `${f.importance * 100}%` }}
              />
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

  // Queries
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

  // Stats
  const stats: Stat[] = useMemo(
    () => [
      { icon: Brain, label: "记忆总量", value: profile?.memory_count ?? 0, sub: "事实 · 偏好 · 情节", color: "bg-bg-info text-text-info" },
      { icon: Bookmark, label: "静态事实", value: profile?.static.length ?? 0, sub: "始终相关的用户信息", color: "bg-bg-success text-text-success" },
      { icon: Activity, label: "动态上下", value: profile?.dynamic.length ?? 0, sub: "近期活动和状态", color: "bg-bg-warning text-text-warning" },
      { icon: Layers, label: "记忆类型", value: "3 种", sub: "事实 · 偏好 · 情节", color: "bg-bg-info text-text-info" },
    ],
    [profile]
  );

  // Of the day
  const memoryOfDay = memories.length > 0 ? memories[0] : null;

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0 }}>
        <div className="flex items-end justify-between">
          <div>
            <Label level="3" weight="medium">首页</Label>
            <Heading level="h1" weight="bold" className="mt-0.5">
              {demoMode ? "Emerald Demo" : `实体 ${entityId}`}
            </Heading>
          </div>
          <div className="flex items-center gap-2 text-xs text-fg-subtle">
            <Clock className="h-3 w-3" />
            {new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" })}
          </div>
        </div>
      </motion.div>

      {/* ── Stats ── */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} delay={i * 0.05} />)
          : stats.map((s, i) => <StatCard key={s.label} {...s} />)}
      </div>

      {/* ── Daily Brief + Overview ── */}
      <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.05 }}>
        <div className="flex flex-col gap-3 lg:flex-row">
          <div className="flex-[3] min-w-0">
            {isLoading ? (
              <div className="rounded-xl border border-surface-border bg-surface-card p-4">
                <Skeleton className="mb-2 h-4 w-24" />
                <Skeleton lines={2} className="h-3" />
              </div>
            ) : (
              <HighlightsCard memories={memories} />
            )}
          </div>
          <div className="flex-[2] min-w-0">
            {isLoading ? (
              <div className="rounded-xl border border-surface-border bg-surface-card p-4">
                <Skeleton className="mb-2 h-4 w-20" />
                <Skeleton lines={2} className="h-3" />
              </div>
            ) : memoryOfDay ? (
              <MemoryOfDayCard memory={memoryOfDay} />
            ) : (
              <div className="rounded-xl border border-dashed border-surface-border p-4 text-center text-xs text-fg-subtle">
                暂无记忆回顾
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {/* ── Quick Actions ── */}
      <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.1 }}>
        <Card>
          <CardContent className="flex flex-wrap items-center gap-1 p-3">
            <Link href="/memories">
              <Button variant="ghost" size="sm">
                <Search className="h-4 w-4" />
                搜索记忆
              </Button>
            </Link>
            <Separator orientation="vertical" className="h-5" />
            <Link href="/graph">
              <Button variant="ghost" size="sm">
                <Network className="h-4 w-4" />
                知识图谱
              </Button>
            </Link>
            <Separator orientation="vertical" className="h-5" />
            <Link href="/settings">
              <Button variant="ghost" size="sm">
                <Zap className="h-4 w-4" />
                API 设置
              </Button>
            </Link>
            <div className="ml-auto hidden items-center gap-1.5 text-xs text-fg-subtle md:flex">
              <Lightbulb className="h-3 w-3 text-amber-500" />
              <span>Tips: 点击记忆卡片查看详情</span>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* ── Recently Saved + Profile Facts ── */}
      <div className="grid gap-6 lg:grid-cols-5">
        {/* Recently Saved */}
        <div className="lg:col-span-3">
          <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.15 }}>
            <div className="mb-3 flex items-center justify-between">
              <Label level="3" weight="medium">最近记忆</Label>
              <Link
                href="/memories"
                className="flex items-center gap-1 text-xs text-brand-accent hover:underline"
              >
                查看全部 <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            <div className="space-y-1.5">
              {isLoading
                ? Array.from({ length: 3 }).map((_, i) => <MemoryRowSkeleton key={i} delay={i * 0.05} />)
                : memories.length > 0
                  ? memories.map((mem, i) => <MemoryRow key={mem.id} memory={mem} index={i} />)
                  : (
                    <div className="flex flex-col items-center justify-center py-12 text-fg-subtle">
                      <Brain className="mb-2 h-8 w-8" />
                      <p className="text-sm">暂无记忆数据</p>
                    </div>
                  )}
            </div>
          </motion.div>
        </div>

        {/* Profile Facts */}
        <div className="lg:col-span-2">
          <motion.div {...fadeUp} transition={{ ...fadeUp.transition, delay: 0.2 }}>
            <StatFactsCard />
          </motion.div>
        </div>
      </div>

      {/* Bottom padding */}
      <div className="h-8" />
    </div>
  );
}
