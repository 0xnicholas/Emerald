"use client";

import { useEffect, useState } from "react";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getClient, resetClient, EmeraldClient, EmeraldApiError } from "@/lib/api";
import {
  Save,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader,
  Eye,
  EyeOff,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";

export default function SettingsPage() {
  const { connected, hydrateFromStorage } = useAppStore();

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  if (!connected) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 p-4 dark:bg-zinc-950">
        <ConnectionPanel />
      </div>
    );
  }

  return <SettingsShell />;
}

function SettingsShell() {
  const {
    apiKey,
    baseUrl,
    entityId,
    connected,
    setApiKey,
    setBaseUrl,
    setEntityId,
    setConnected,
  } = useAppStore();

  const [localKey, setLocalKey] = useState(apiKey);
  const [localUrl, setLocalUrl] = useState(baseUrl);
  const [localEntity, setLocalEntity] = useState(entityId);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<"success" | "error" | null>(
    null
  );

  // Health check
  const healthQuery = useQuery({
    queryKey: ["health", baseUrl],
    queryFn: () => getClient().health(),
    enabled: connected,
    refetchInterval: 30_000,
  });

  const handleSave = () => {
    setApiKey(localKey);
    setBaseUrl(localUrl);
    setEntityId(localEntity);
    resetClient();
    setConnected(false);
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      resetClient();
      const client = new EmeraldClient({
        apiKey: localKey,
        baseUrl: localUrl,
        entityId: localEntity,
      }, 5_000);
      await client.health();
      setTestResult("success");
    } catch {
      setTestResult("error");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto">
        <div className="flex-1 p-6">
          <h1 className="text-2xl font-bold tracking-tight">设置</h1>
          <p className="mt-1 text-sm text-zinc-500">管理 Emerald 连接和配置</p>

          <div className="mt-8 space-y-6">
            {/* Connection */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  连接配置
                  {healthQuery.data?.status === "healthy" ? (
                    <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                      <CheckCircle2 className="mr-1 h-3 w-3" />
                      已连接 v{healthQuery.data.version}
                    </Badge>
                  ) : (
                    <Badge className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
                      <XCircle className="mr-1 h-3 w-3" />
                      未连接
                    </Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-zinc-500">
                    API 地址
                  </label>
                  <Input
                    value={localUrl}
                    onChange={(e) => setLocalUrl(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-zinc-500">
                    API Key
                  </label>
                  <div className="flex gap-2">
                    <Input
                      value={localKey}
                      onChange={(e) => setLocalKey(e.target.value)}
                      type={showKey ? "text" : "password"}
                      className="flex-1"
                    />
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setShowKey(!showKey)}
                    >
                      {showKey ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-zinc-500">
                    实体 ID（默认）
                  </label>
                  <Input
                    value={localEntity}
                    onChange={(e) => setLocalEntity(e.target.value)}
                    placeholder="user_alex"
                  />
                </div>

                <div className="flex gap-2">
                  <Button onClick={handleSave}>
                    <Save className="h-4 w-4" />
                    保存
                  </Button>
                  <Button variant="outline" onClick={handleTest} disabled={testing}>
                    {testing ? (
                      <Loader className="h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                    测试连接
                  </Button>
                </div>

                {testResult === "success" && (
                  <p className="text-sm text-emerald-600">✅ 连接成功</p>
                )}
                {testResult === "error" && (
                  <p className="text-sm text-red-600">❌ 连接失败</p>
                )}
              </CardContent>
            </Card>

            {/* API Info */}
            <Card>
              <CardHeader>
                <CardTitle>API 参考</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-zinc-600 dark:text-zinc-400">
                <p>
                  Emerald 提供 REST API，您也可以直接通过 Swagger UI 探索端点：
                </p>
                <code className="block rounded bg-zinc-100 p-2 text-xs dark:bg-zinc-800">
                  {baseUrl}/docs
                </code>
                <p>核心端点：</p>
                <ul className="list-inside list-disc space-y-1 text-xs">
                  <li>
                    <code className="font-mono">POST /v1/memories</code> —
                    添加记忆
                  </li>
                  <li>
                    <code className="font-mono">POST /v1/search</code> — 混合搜索
                  </li>
                  <li>
                    <code className="font-mono">GET /v1/profiles/{"{id}"}</code>{" "}
                    — 用户画像
                  </li>
                  <li>
                    <code className="font-mono">POST /v1/upload</code> — 文件上传
                  </li>
                </ul>
              </CardContent>
            </Card>

            {/* Dark mode toggle placeholder */}
            <Card>
              <CardHeader>
                <CardTitle>显示</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-zinc-500">
                  深色模式跟随系统设置。
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}
