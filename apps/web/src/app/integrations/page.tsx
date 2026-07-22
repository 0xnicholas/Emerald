"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { MobileBottomNav } from "@/components/layout/mobile-bottom-nav";
import { DemoBanner } from "@/components/layout/demo-banner";
import { getClient } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/typography";
import {
  Loader, CheckCircle2, XCircle, ExternalLink, Plug,
  Mail, HardDrive, BookOpen, Terminal, RefreshCw, Code2,
} from "lucide-react";
import { toast } from "sonner";

interface ConnectorStatus {
  provider: string;
  sync_status: string;
  last_synced_at: string | null;
  error_message: string | null;
  connected_at: string | null;
}

const CONNECTOR_META: Record<string, {
  name: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  docsUrl: string;
}> = {
  "google-drive": {
    name: "Google Drive",
    description: "Sync documents, spreadsheets, and presentations",
    icon: <HardDrive className="h-5 w-5" />,
    color: "text-yellow-500",
    docsUrl: "https://supermemory.ai/docs/connectors/google-drive",
  },
  "notion": {
    name: "Notion",
    description: "Import pages and databases from your workspace",
    icon: <BookOpen className="h-5 w-5" />,
    color: "text-white",
    docsUrl: "https://supermemory.ai/docs/connectors/notion",
  },
  "github": {
    name: "GitHub",
    description: "Index repositories, issues, and pull requests",
    icon: <Code2 className="h-5 w-5" />,
    color: "text-white",
    docsUrl: "https://supermemory.ai/docs/connectors/github",
  },
  "gmail": {
    name: "Gmail",
    description: "Search and remember email conversations",
    icon: <Mail className="h-5 w-5" />,
    color: "text-red-400",
    docsUrl: "https://supermemory.ai/docs/connectors/gmail",
  },
};

export default function IntegrationsPage() {
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

  return <IntegrationsShell />;
}

function IntegrationsShell() {
  const entityId = useAppStore((s) => s.entityId);
  const baseUrl = useAppStore((s) => s.baseUrl);
  const queryClient = useQueryClient();

  const connectors = useQuery({
    queryKey: ["connectors", entityId],
    queryFn: async () => {
      const statuses: ConnectorStatus[] = [];
      for (const provider of Object.keys(CONNECTOR_META)) {
        try {
          const data = await getClient().getConnectorStatus(provider);
          statuses.push({ provider, ...data });
        } catch {
          statuses.push({
            provider,
            sync_status: "inactive",
            last_synced_at: null,
            error_message: null,
            connected_at: null,
          });
        }
      }
      return statuses;
    },
    enabled: !!entityId,
    staleTime: 10_000,
  });

  const activeCount = connectors.data?.filter(
    (c) => c.sync_status === "active" || c.sync_status === "syncing"
  ).length ?? 0;

  if (connectors.isLoading) {
    return <Shell children={<LoadingState />} />;
  }

  return (
    <Shell>
      <div className="mx-auto w-full max-w-3xl flex-1 p-4 md:p-6 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-fg-primary">Integrations</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Connect external services to enrich Emerald with more context
          </p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3">
          <Card className="col-span-1">
            <CardContent className="p-4 text-center">
              <p className="text-2xl font-bold text-fg-primary">{Object.keys(CONNECTOR_META).length}</p>
              <p className="text-xs text-fg-muted">Available connectors</p>
            </CardContent>
          </Card>
          <Card className="col-span-1">
            <CardContent className="p-4 text-center">
              <p className="text-2xl font-bold text-brand-accent">{activeCount}</p>
              <p className="text-xs text-fg-muted">Active connections</p>
            </CardContent>
          </Card>
          <Card className="col-span-1">
            <CardContent className="p-4 text-center">
              <p className="text-2xl font-bold text-fg-primary">
                {connectors.data?.length
                  ? connectors.data.filter((c) => c.sync_status === "error").length
                  : 0}
              </p>
              <p className="text-xs text-fg-muted">With errors</p>
            </CardContent>
          </Card>
        </div>

        {/* Connector list */}
        <div className="space-y-2">
          <Label level="2" weight="medium" className="text-fg-faint">CONNECTORS</Label>
          <div className="space-y-2">
            {Object.entries(CONNECTOR_META).map(([provider, meta]) => {
              const status = connectors.data?.find((c) => c.provider === provider);
              const isActive = status?.sync_status === "active";
              const isError = status?.sync_status === "error";

              return (
                <Card key={provider}>
                  <CardContent className="flex items-center gap-4 p-4">
                    <div className={`flex h-10 w-10 items-center justify-center rounded-xl bg-surface-hover ${meta.color}`}>
                      {meta.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-fg-primary">{meta.name}</p>
                        {isActive ? (
                          <Badge className="bg-bg-success text-text-success text-[10px] px-1.5 py-0">
                            <CheckCircle2 className="h-3 w-3 mr-0.5" />
                            Connected
                          </Badge>
                        ) : isError ? (
                          <Badge className="bg-bg-error text-text-error text-[10px] px-1.5 py-0">
                            <XCircle className="h-3 w-3 mr-0.5" />
                            Error
                          </Badge>
                        ) : (
                          <Badge className="bg-surface-hover text-fg-faint text-[10px] px-1.5 py-0">
                            Inactive
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-fg-muted mt-0.5">{meta.description}</p>
                      {status?.last_synced_at && (
                        <p className="text-[10px] text-fg-faint mt-0.5">
                          Last synced: {new Date(status.last_synced_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {isActive ? (
                        <DisconnectButton provider={provider} />
                      ) : (
                        <Button variant="outline" size="sm" disabled>
                          <Plug className="h-3.5 w-3.5 mr-1" />
                          Connect
                        </Button>
                      )}
                      <a href={meta.docsUrl} target="_blank" rel="noopener noreferrer">
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      </a>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>

        {/* API Reference */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-fg-primary">
              <Terminal className="h-5 w-5" />
              API Reference
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-fg-muted">
            <p>Use the REST API to programmatically add and search memories.</p>
            <code className="block rounded-lg bg-surface-hover/50 p-3 text-xs font-mono text-fg-muted">
              {baseUrl}/docs
            </code>
            <div className="grid grid-cols-2 gap-2">
              {[
                { method: "POST", path: "/v1/memories", desc: "Add a memory" },
                { method: "POST", path: "/v1/search", desc: "Hybrid search" },
                { method: "GET", path: "/v1/profiles/{id}", desc: "User profile" },
                { method: "POST", path: "/v1/upload", desc: "File upload" },
              ].map((ep) => (
                <div key={ep.path} className="rounded-lg bg-surface-hover/50 p-2.5">
                  <span className="text-[10px] font-bold text-brand-accent">{ep.method}</span>
                  <p className="text-xs font-mono text-fg-muted truncate">{ep.path}</p>
                  <p className="text-[10px] text-fg-faint">{ep.desc}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </Shell>
  );
}

function DisconnectButton({ provider }: { provider: string }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  const disconnect = useMutation({
    mutationFn: async () => {
      await getClient().disconnectConnector(provider);
    },
    onMutate: () => setPending(true),
    onSuccess: () => {
      toast.success(`${provider} disconnected`);
      queryClient.invalidateQueries({ queryKey: ["connectors"] });
    },
    onError: () => toast.error("Failed to disconnect"),
    onSettled: () => setPending(false),
  });

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => disconnect.mutate()}
      disabled={pending}
      className="border-red-800/40 text-red-400 hover:bg-red-950/30"
    >
      {pending ? <Loader className="h-3.5 w-3.5 animate-spin mr-1" /> : null}
      Disconnect
    </Button>
  );
}

// ─── Shell ───────────────────────────────────────────────────────────

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto pb-16 md:pb-0">
        <DemoBanner />
        {children}
      </main>
      <MobileBottomNav />
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <Loader className="h-5 w-5 animate-spin text-fg-muted" />
    </div>
  );
}
