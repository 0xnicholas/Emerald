"use client";

import { Sidebar } from "@/components/layout/sidebar";
import { DemoBanner } from "@/components/layout/demo-banner";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { useEffect } from "react";
import { MOCK_PROFILE, MOCK_MEMORIES } from "@/lib/mock-data";

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
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto">
        <DemoBanner />
        <div className="flex-1 p-6">
          <div className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
            <p className="mt-1 text-sm text-zinc-500">
              实体: <code className="font-mono text-emerald-600">{entityId}</code>
            </p>
          </div>

          <DashboardContent />
        </div>
      </main>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Brain, Search, User, Activity } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { formatDate, memoryTypeLabel, memoryTypeColor } from "@/lib/utils";

function DashboardContent() {
  const { entityId, demoMode } = useAppStore();

  const profileQuery = useQuery({
    queryKey: ["profile", entityId],
    queryFn: () => getClient().getProfile(entityId),
    enabled: !!entityId && !demoMode,
  });

  const searchDemoQuery = useQuery({
    queryKey: ["search-demo", entityId],
    queryFn: () =>
      getClient().search("", entityId, { searchMode: "memory", topK: 8 }),
    enabled: !!entityId && !demoMode,
  });

  const profile = demoMode ? MOCK_PROFILE : profileQuery.data;
  const recentMemories = demoMode
    ? MOCK_MEMORIES.slice(0, 8)
    : (searchDemoQuery.data?.results ?? []);

  const stats = [
    {
      label: "记忆总数",
      value: profile?.memory_count ?? "…",
      icon: Brain,
      color: "text-emerald-600",
      bg: "bg-emerald-50 dark:bg-emerald-950/30",
    },
    {
      label: "静态事实",
      value: profile?.static.length ?? "…",
      icon: User,
      color: "text-blue-600",
      bg: "bg-blue-50 dark:bg-blue-950/30",
    },
    {
      label: "动态上下文",
      value: profile?.dynamic.length ?? "…",
      icon: Activity,
      color: "text-amber-600",
      bg: "bg-amber-50 dark:bg-amber-950/30",
    },
    {
      label: "搜索可用",
      value: "混合搜索",
      icon: Search,
      color: "text-purple-600",
      bg: "bg-purple-50 dark:bg-purple-950/30",
    },
  ];

  return (
    <div className="space-y-8">
      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardContent className="flex items-center gap-4 p-5">
              <div className={`rounded-lg p-2.5 ${s.bg}`}>
                <s.icon className={`h-5 w-5 ${s.color}`} />
              </div>
              <div>
                <p className="text-2xl font-bold">{s.value}</p>
                <p className="text-xs text-zinc-500">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Quick actions */}
      <div className="flex gap-3">
        <Link href="/memories">
          <Button variant="default">
            <Search className="h-4 w-4" />
            浏览记忆
          </Button>
        </Link>
        <Link href="/graph">
          <Button variant="secondary">
            <Brain className="h-4 w-4" />
            查看图谱
          </Button>
        </Link>
      </div>

      {/* Recent memories */}
      <div>
        <h2 className="mb-4 text-lg font-semibold">最近记忆</h2>
        <div className="space-y-2">
          {recentMemories.slice(0, 5).map((mem) => (
            <Card key={mem.id} className="transition-shadow hover:shadow-sm">
              <CardContent className="flex items-start gap-3 p-4">
                <Badge className={memoryTypeColor(mem.memory_type)}>
                  {memoryTypeLabel(mem.memory_type)}
                </Badge>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-zinc-700 dark:text-zinc-300 truncate">
                    {mem.content}
                  </p>
                  {mem.summary && (
                    <p className="mt-0.5 text-xs text-zinc-400 truncate">
                      {mem.summary}
                    </p>
                  )}
                </div>
                <span className="shrink-0 text-xs text-zinc-400">
                  {Math.round((mem.score ?? 0) * 100)}%
                </span>
              </CardContent>
            </Card>
          ))}

          {recentMemories.length === 0 && !searchDemoQuery.isLoading && (
            <p className="py-8 text-center text-sm text-zinc-400">
              暂无记忆数据。通过 API 添加内容后，它们会出现在这里。
            </p>
          )}
        </div>
      </div>

      {/* Static facts from profile */}
      {profile && profile.static.length > 0 && (
        <div>
          <h2 className="mb-4 text-lg font-semibold">画像 — 静态事实</h2>
          <div className="space-y-2">
            {profile.static.map((f, i) => (
              <Card key={i}>
                <CardContent className="flex items-center justify-between p-4">
                  <p className="text-sm text-zinc-700 dark:text-zinc-300">
                    {f.content}
                  </p>
                  <span className="ml-3 shrink-0 text-xs text-zinc-400">
                    重要度: {Math.round(f.importance * 100)}%
                  </span>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
