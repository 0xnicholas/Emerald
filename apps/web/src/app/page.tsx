"use client";

import { Sidebar } from "@/components/layout/sidebar";
import { DemoBanner } from "@/components/layout/demo-banner";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { useEffect, useMemo } from "react";
import { MOCK_PROFILE, MOCK_MEMORIES } from "@/lib/mock-data";
import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Brain,
  Search,
  User,
  Activity,
  Sparkles,
  ArrowRight,
  Clock,
  TrendingUp,
  Zap,
  Layers,
  Star,
  BarChart3,
  Network,
  Bookmark,
  MessageSquare,
  FileText,
  Code,
} from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";
import type { SearchMemory } from "@/lib/types";
import { motion } from "motion/react";

// ─── Layout ─────────────────────────────────────────────────────────

export default function HomePage() {
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

  return <AppShell />;
}

function AppShell() {
  const entityId = useAppStore((s) => s.entityId);

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto">
        <DemoBanner />
        <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col p-6">
          <DashboardContent entityId={entityId} />
        </div>
      </main>
    </div>
  );
}

// ─── Stat Card ───────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
  trend,
}: {
  icon: typeof Brain;
  label: string;
  value: string | number;
  sub?: string;
  color: string;
  trend?: "up" | "down";
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card className="group transition-all hover:shadow-md">
        <CardContent className="p-5">
          <div className="flex items-start justify-between">
            <div className={`rounded-xl p-3 ${color}`}>
              <Icon className="h-5 w-5" />
            </div>
            {trend && (
              <span
                className={`flex items-center gap-0.5 text-xs font-medium ${
                  trend === "up"
                    ? "text-emerald-600"
                    : "text-red-600"
                }`}
              >
                <TrendingUp className="h-3 w-3" />
              </span>
            )}
          </div>
          <div className="mt-4">
            <p className="text-2xl font-bold tracking-tight">{value}</p>
            <p className="mt-0.5 text-sm text-zinc-500">{label}</p>
            {sub && (
              <p className="mt-1 text-xs text-zinc-400">{sub}</p>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

// ─── Memory Row ──────────────────────────────────────────────────────

function MemoryRow({
  memory,
  index,
}: {
  memory: SearchMemory;
  index: number;
}) {
  const typeColors: Record<string, string> = {
    fact: "border-l-emerald-400",
    preference: "border-l-purple-400",
    episodic: "border-l-amber-400",
  };
  const icons: Record<string, typeof Brain> = {
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
      className={`group flex items-start gap-4 rounded-xl border border-zinc-100 border-l-4 bg-white p-4 transition-all hover:border-zinc-200 hover:shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700 ${
        typeColors[memory.memory_type] ?? "border-l-zinc-400"
      }`}
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
          {memory.content}
        </p>
        {memory.summary && (
          <p className="mt-1 text-xs text-zinc-400">{memory.summary}</p>
        )}
        <div className="mt-2 flex items-center gap-2">
          <Badge className={memoryTypeColor(memory.memory_type)}>
            {memoryTypeLabel(memory.memory_type)}
          </Badge>
          {memory.source && (
            <span className="text-xs text-zinc-400">
              {memory.source === "rag" ? "RAG" : "记忆"}
            </span>
          )}
          {memory.score !== undefined && (
            <span className="ml-auto text-xs font-medium text-zinc-400">
              {Math.round(memory.score * 100)}% 置信度
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ─── Dashboard Content ───────────────────────────────────────────────

function DashboardContent({ entityId }: { entityId: string }) {
  const demoMode = useAppStore((s) => s.demoMode);

  const profileQuery = useQuery({
    queryKey: ["profile", entityId],
    queryFn: () => getClient().getProfile(entityId),
    enabled: !!entityId && !demoMode,
  });

  const searchQuery = useQuery({
    queryKey: ["search-demo", entityId],
    queryFn: () =>
      getClient().search("", entityId, { searchMode: "memory", topK: 8 }),
    enabled: !!entityId && !demoMode,
  });

  const profile = demoMode ? MOCK_PROFILE : profileQuery.data;
  const recentMemories = demoMode
    ? MOCK_MEMORIES.slice(0, 8)
    : (searchQuery.data?.results ?? []);

  // Stats data
  const statsCards = useMemo(
    () => [
      {
        icon: Brain,
        label: "记忆总量",
        value: profile?.memory_count ?? 0,
        sub: "包含事实、偏好和情节",
        color: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
        trend: "up" as const,
      },
      {
        icon: User,
        label: "静态事实",
        value: profile?.static.length ?? 0,
        sub: "始终相关的用户信息",
        color: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
      },
      {
        icon: Activity,
        label: "动态上下文",
        value: profile?.dynamic.length ?? 0,
        sub: "近期活动和状态",
        color: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
      },
      {
        icon: Layers,
        label: "记忆类型",
        value: "3 种",
        sub: "事实 · 偏好 · 情节",
        color: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
      },
    ],
    [profile]
  );

  return (
    <div className="space-y-8">
      {/* ── Welcome ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {demoMode ? (
              <>
                Demo 模式 · 浏览{" "}
                <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-emerald-600 dark:bg-zinc-800 dark:text-emerald-400">
                  {entityId || "demo_user"}
                </code>
              </>
            ) : (
              <>
                实体{" "}
                <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-emerald-600 dark:bg-zinc-800 dark:text-emerald-400">
                  {entityId}
                </code>
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden text-xs text-zinc-400 sm:inline">
            {new Date().toLocaleDateString("zh-CN", {
              month: "long",
              day: "numeric",
              weekday: "short",
            })}
          </span>
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
        </div>
      </div>

      {/* ── Stats Grid ── */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statsCards.map((s, i) => (
          <StatCard key={s.label} {...s} />
        ))}
      </div>

      {/* ── Quick Actions ── */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            <Zap className="h-4 w-4 text-amber-500" />
            快速操作
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link href="/memories">
              <Button variant="default" size="sm">
                <Search className="h-4 w-4" />
                浏览记忆
              </Button>
            </Link>
            <Link href="/graph">
              <Button variant="secondary" size="sm">
                <Network className="h-4 w-4" />
                知识图谱
              </Button>
            </Link>
            <Link href="/settings">
              <Button variant="outline" size="sm">
                <Code className="h-4 w-4" />
                API 设置
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* ── Recent Memories ── */}
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">最近记忆</h2>
          <Link
            href="/memories"
            className="flex items-center gap-1 text-xs font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400"
          >
            查看全部
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        <div className="space-y-2">
          {recentMemories.map((mem, i) => (
            <MemoryRow key={mem.id} memory={mem} index={i} />
          ))}
          {recentMemories.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-zinc-400">
              <Brain className="mb-2 h-8 w-8" />
              <p className="text-sm">暂无记忆数据</p>
              <p className="mt-1 text-xs">
                通过 API 添加内容后，它们会出现在这里
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Two Column: Static + Dynamic ── */}
      {profile && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Static Facts */}
          <div>
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              <Bookmark className="h-4 w-4 text-blue-500" />
              静态画像事实
              <Badge className="ml-auto bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                {profile.static.length}
              </Badge>
            </div>
            <div className="space-y-2">
              {profile.static.map((f, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.04 }}
                  className="rounded-lg border border-zinc-100 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm text-zinc-700 dark:text-zinc-300">
                      {f.content}
                    </p>
                    <span className="shrink-0 text-xs font-medium text-zinc-400">
                      {Math.round(f.importance * 100)}%
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                    <div
                      className="h-full rounded-full bg-blue-500"
                      style={{ width: `${f.importance * 100}%` }}
                    />
                  </div>
                </motion.div>
              ))}
            </div>
          </div>

          {/* Dynamic Context */}
          <div>
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              <Activity className="h-4 w-4 text-amber-500" />
              动态上下文
              <Badge className="ml-auto bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                {profile.dynamic.length}
              </Badge>
            </div>
            <div className="space-y-2">
              {profile.dynamic.map((d, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="rounded-lg border border-zinc-100 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm text-zinc-700 dark:text-zinc-300">
                      {d.content}
                    </p>
                    <span className="shrink-0 text-xs font-medium text-zinc-400">
                      {Math.round(d.relevance * 100)}%
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-2">
                    {d.source && (
                      <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800">
                        {d.source}
                      </span>
                    )}
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                      <div
                        className="h-full rounded-full bg-amber-500"
                        style={{ width: `${d.relevance * 100}%` }}
                      />
                    </div>
                  </div>
                </motion.div>
              ))}
              {profile.dynamic.length === 0 && (
                <p className="py-8 text-center text-sm text-zinc-400">
                  暂无动态上下文
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Bottom spacer ── */}
      <div className="h-4" />
    </div>
  );
}
