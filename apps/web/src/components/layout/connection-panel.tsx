"use client";

import { useAppStore } from "@/stores/app";
import { getClient, resetClient, EmeraldClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Plug, PlugZap, Loader, EyeIcon } from "lucide-react";
import { useState } from "react";

export function ConnectionPanel() {
  const {
    apiKey,
    baseUrl,
    entityId,
    connected,
    setApiKey,
    setBaseUrl,
    setEntityId,
    setConnected,
    setDemoMode,
    hydrateFromStorage,
  } = useAppStore();

  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");

  // Hydrate on first render
  useState(() => {
    hydrateFromStorage();
  });

  const testConnection = async () => {
    setTesting(true);
    setError("");
    try {
      resetClient();
      const client = new EmeraldClient({
        apiKey,
        baseUrl,
        entityId,
      }, 5_000);
      const health = await client.health();
      if (health.status === "healthy") {
        setConnected(true);
      } else {
        setError(`API 返回异常状态: ${health.status}`);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "连接失败";
      setError(msg);
      setConnected(false);
    } finally {
      setTesting(false);
    }
  };

  if (connected) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-surface-border bg-surface-card px-3 py-1.5 text-sm">
        <PlugZap className="h-4 w-4 text-brand-accent" />
        <span className="text-fg-primary">
          已连接
        </span>
        <Badge className="bg-brand-accent-subtle text-brand-accent">
          {entityId || "未指定实体"}
        </Badge>
        <button
          onClick={() => setConnected(false)}
          className="ml-2 text-xs text-fg-subtle underline hover:text-fg-muted"
        >
          断开
        </button>
      </div>
    );
  }

  return (
    <Card className="mx-auto mt-8 max-w-md">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Plug className="h-5 w-5" />
          连接到 Emerald
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-fg-muted">API 地址</label>
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="留空 = 同源（经 nginx 代理）"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-fg-muted">API Key</label>
          <Input
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="em_xxxxxxxx"
            type="password"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-fg-muted">
            实体 ID（用户/项目）
          </label>
          <Input
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            placeholder="user_alex"
          />
        </div>

        {error && (
          <p className="text-sm text-text-error">{error}</p>
        )}

        <Button onClick={testConnection} disabled={testing} className="w-full">
          {testing ? (
            <>
              <Loader className="h-4 w-4 animate-spin" />
              连接中…
            </>
          ) : (
            "测试连接"
          )}
        </Button>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-surface-border" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-surface-card px-2 text-fg-subtle">
              或
            </span>
          </div>
        </div>

        <Button
          variant="outline"
          onClick={() => setDemoMode(true)}
          className="w-full"
        >
          <EyeIcon className="h-4 w-4" />
          Demo 预览模式
        </Button>
      </CardContent>
    </Card>
  );
}
