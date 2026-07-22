"use client";

import { useEffect, useState } from "react";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { MobileBottomNav } from "@/components/layout/mobile-bottom-nav";
import { DemoBanner } from "@/components/layout/demo-banner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Label } from "@/components/ui/typography";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { getClient, resetClient, EmeraldClient } from "@/lib/api";
import {
  Save, CheckCircle2, XCircle, Loader, Eye, EyeOff,
  Server, Key, Info, RefreshCw, Link2, Terminal, Download, Upload,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";

export default function SettingsPage() {
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

  return <SettingsShell />;
}

function SettingsShell() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto pb-16 md:pb-0">
        <DemoBanner />
        <div className="mx-auto w-full max-w-3xl flex-1 p-4 md:p-6">
          <div className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight text-fg-primary">Settings</h1>
            <p className="mt-1 text-sm text-fg-muted">Manage your Emerald connection and configuration</p>
          </div>

          <Tabs defaultValue="connection">
            <TabsList className="w-full">
              <TabsTrigger value="connection" className="flex-1">
                <Server className="h-4 w-4 mr-1.5" />
                Connection
              </TabsTrigger>
              <TabsTrigger value="api" className="flex-1">
                <Key className="h-4 w-4 mr-1.5" />
                API Keys
              </TabsTrigger>
              <TabsTrigger value="info" className="flex-1">
                <Info className="h-4 w-4 mr-1.5" />
                System Info
              </TabsTrigger>
              <TabsTrigger value="data" className="flex-1">
                <Download className="h-4 w-4 mr-1.5" />
                Data
              </TabsTrigger>
            </TabsList>

            <TabsContent value="connection" className="mt-6">
              <ConnectionSettings />
            </TabsContent>

            <TabsContent value="api" className="mt-6">
              <ApiKeysPanel />
            </TabsContent>

            <TabsContent value="info" className="mt-6">
              <SystemInfoPanel />
            </TabsContent>

            <TabsContent value="data" className="mt-6">
              <DataPanel />
            </TabsContent>
          </Tabs>
        </div>
      </main>
      <MobileBottomNav />
    </div>
  );
}

function ConnectionSettings() {
  const {
    apiKey, baseUrl, entityId, connected,
    setApiKey, setBaseUrl, setEntityId, setConnected,
  } = useAppStore();

  const [localKey, setLocalKey] = useState(apiKey);
  const [localUrl, setLocalUrl] = useState(baseUrl);
  const [localEntity, setLocalEntity] = useState(entityId);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<"success" | "error" | null>(null);

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
      const client = new EmeraldClient({ apiKey: localKey, baseUrl: localUrl, entityId: localEntity }, 5_000);
      await client.health();
      setTestResult("success");
    } catch {
      setTestResult("error");
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-fg-primary">
          Connection
          {connected ? (
            <Badge className="bg-bg-success text-text-success"><CheckCircle2 className="mr-1 h-3 w-3" />Connected</Badge>
          ) : (
            <Badge className="bg-bg-error text-text-error"><XCircle className="mr-1 h-3 w-3" />Disconnected</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label>API URL</Label>
          <Input value={localUrl} onChange={(e) => setLocalUrl(e.target.value)} placeholder="http://localhost:8000" />
        </div>
        <div className="space-y-1.5">
          <Label>API Key</Label>
          <div className="flex gap-2">
            <Input value={localKey} onChange={(e) => setLocalKey(e.target.value)} type={showKey ? "text" : "password"} className="flex-1" />
            <Button variant="outline" size="icon" onClick={() => setShowKey(!showKey)}>
              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label>Entity ID</Label>
          <Input value={localEntity} onChange={(e) => setLocalEntity(e.target.value)} placeholder="user_alex" />
        </div>

        <div className="flex gap-2">
          <Button onClick={handleSave}><Save className="h-4 w-4" /> Save</Button>
          <Button variant="outline" onClick={handleTest} disabled={testing}>
            {testing ? <Loader className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Test Connection
          </Button>
        </div>

        {testResult === "success" && <p className="text-sm text-text-success">✅ Connection successful</p>}
        {testResult === "error" && <p className="text-sm text-text-error">❌ Connection failed</p>}
      </CardContent>
    </Card>
  );
}

function ApiKeysPanel() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-fg-primary">
          <Key className="h-5 w-5" />
          API Keys
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-fg-muted">
          API keys are managed through the Emerald backend. Generate keys using the CLI or seed script.
        </p>
        <div className="rounded-lg bg-surface-hover/50 p-3">
          <Label level="3">Quick Start</Label>
          <code className="mt-1 block rounded bg-surface-card p-2 text-xs text-fg-muted font-mono">
            docker exec emerald-api python scripts/seed_dev_api_key.py
          </code>
        </div>
      </CardContent>
    </Card>
  );
}

function SystemInfoPanel() {
  const { baseUrl } = useAppStore();
  const demoMode = useAppStore((s) => s.demoMode);

  const healthQuery = useQuery({
    queryKey: ["settings-health", baseUrl],
    queryFn: () => getClient().health(),
    enabled: !demoMode,
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-fg-primary">System Health</CardTitle>
        </CardHeader>
        <CardContent>
          {demoMode ? (
            <p className="text-sm text-fg-muted">Demo mode — connect to a backend to see system status.</p>
          ) : healthQuery.data ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-text-success" />
                <span className="text-sm text-fg-primary">API v{healthQuery.data.version}</span>
              </div>
              {healthQuery.data.checks && Object.entries(healthQuery.data.checks as Record<string, string>).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-sm">
                  <div className={`h-2 w-2 rounded-full ${v === "ok" ? "bg-text-success" : "bg-text-error"}`} />
                  <span className="text-fg-muted capitalize">{k}</span>
                  <span className="text-fg-subtle text-xs">{v}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-sm text-fg-muted">
              <Loader className="h-4 w-4 animate-spin" />
              Checking health...
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-fg-primary">API Reference</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-fg-muted">
          <p>Emerald provides a REST API. Explore endpoints via Swagger UI:</p>
          <code className="block rounded-lg bg-surface-hover/50 p-2 text-xs text-fg-muted font-mono">
            {baseUrl}/docs
          </code>
          <div className="grid grid-cols-2 gap-2 pt-2">
            {[
              { method: "POST", path: "/v1/memories", desc: "Add memory" },
              { method: "POST", path: "/v1/search", desc: "Hybrid search" },
              { method: "GET", path: "/v1/profiles/{id}", desc: "User profile" },
              { method: "POST", path: "/v1/upload", desc: "File upload" },
            ].map((ep) => (
              <div key={ep.path} className="rounded-lg bg-surface-hover/50 p-2">
                <span className="text-[10px] font-bold text-brand-accent">{ep.method}</span>
                <p className="text-xs text-fg-muted font-mono truncate">{ep.path}</p>
                <p className="text-[10px] text-fg-faint">{ep.desc}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DataPanel() {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      let memories;
      if (demoMode) {
        const { MOCK_MEMORIES } = await import("@/lib/mock-data");
        memories = MOCK_MEMORIES;
      } else {
        const data = await getClient().search("", entityId, {
          searchMode: "memory",
          topK: 500,
        });
        memories = data.results;
      }

      const blob = new Blob([JSON.stringify({ memories, exportedAt: new Date().toISOString() }, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `emerald-memories-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Memories exported!");
    } catch {
      toast.error("Failed to export memories");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-fg-primary">
            <Download className="h-5 w-5" />
            Export Memories
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-fg-muted">
            Download all your memories as a JSON file.
          </p>
          <Button onClick={handleExport} disabled={exporting}>
            {exporting ? <Loader className="h-4 w-4 animate-spin mr-1" /> : <Download className="h-4 w-4 mr-1" />}
            Export as JSON
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
