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
  Loader, CheckCircle2, XCircle, Plug, Mail, RefreshCw, Terminal,
} from "lucide-react";
import { toast } from "sonner";

interface SourceBinding {
  id: string;
  provider: string;
  hub_account_id: string;
  sync_status: string;
  last_synced_at: string | null;
  error_message: string | null;
}

// Connection hub (ADR-0004) — Totem v1 upstream: Feishu Docs only.
const SOURCE_META: Record<string, {
  name: string;
  description: string;
  icon: React.ReactNode;
  color: string;
}> = {
  feishu: {
    name: "Feishu Docs",
    description: "Sync documents from your Feishu workspace via the connection hub",
    icon: <Mail className="h-5 w-5" />,
    color: "text-blue-400",
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

  const sources = useQuery({
    queryKey: ["sources", entityId],
    queryFn: async () => {
      const bindings = await getClient().listSources(entityId!);
      return bindings.map((b) => ({ ...b, provider: b.provider }));
    },
    enabled: !!entityId,
    staleTime: 10_000,
  });

  const activeCount = sources.data?.filter(
    (s) => s.sync_status === "active" || s.sync_status === "syncing"
  ).length ?? 0;

  if (sources.isLoading) {
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
              <p className="text-2xl font-bold text-fg-primary">{Object.keys(SOURCE_META).length}</p>
              <p className="text-xs text-fg-muted">Available sources</p>
            </CardContent>
          </Card>
          <Card className="col-span-1">
            <CardContent className="p-4 text-center">
              <p className="text-2xl font-bold text-brand-accent">{activeCount}</p>
              <p className="text-xs text-fg-muted">Active bindings</p>
            </CardContent>
          </Card>
          <Card className="col-span-1">
            <CardContent className="p-4 text-center">
              <p className="text-2xl font-bold text-fg-primary">
                {sources.data?.length
                  ? sources.data.filter((s) => s.sync_status === "error").length
                  : 0}
              </p>
              <p className="text-xs text-fg-muted">With errors</p>
            </CardContent>
          </Card>
        </div>

        {/* Source list */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label level="2" weight="medium" className="text-fg-faint">SOURCES</Label>
            <RefreshButton />
          </div>
          <div className="space-y-2">
            {(sources.data?.length ? sources.data : [{ provider: "feishu" } as SourceBinding]).map((src) => {
              const meta = SOURCE_META[src.provider] ?? SOURCE_META.feishu;
              const isActive = src.sync_status === "active";
              const isError = src.sync_status === "error";

              return (
                <Card key={src.id ?? src.provider}>
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
                      {src.error_message && (
                        <p className="text-[10px] text-text-error mt-0.5">{src.error_message}</p>
                      )}
                      {src.last_synced_at && (
                        <p className="text-[10px] text-fg-faint mt-0.5">
                          Last synced: {new Date(src.last_synced_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {src.id ? (
                        <DisconnectButton bindingId={src.id} />
                      ) : (
                        <ConnectButton provider={src.provider} />
                      )}
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

function RefreshButton() {
  const entityId = useAppStore((s) => s.entityId);
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  const refresh = useMutation({
    mutationFn: async () => {
      await getClient().refreshSources(entityId!);
    },
    onMutate: () => setPending(true),
    onSuccess: () => {
      toast.success("Bindings refreshed");
      queryClient.invalidateQueries({ queryKey: ["sources"] });
    },
    onError: () => toast.error("Failed to refresh bindings"),
    onSettled: () => setPending(false),
  });

  return (
    <Button variant="ghost" size="sm" onClick={() => refresh.mutate()} disabled={pending}>
      {pending ? <Loader className="h-3.5 w-3.5 animate-spin mr-1" /> : <RefreshCw className="h-3.5 w-3.5 mr-1" />}
      Refresh
    </Button>
  );
}

function ConnectButton({ provider }: { provider: string }) {
  const entityId = useAppStore((s) => s.entityId);
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  const connect = useMutation({
    mutationFn: async () => {
      const session = await getClient().connectSource(entityId!, provider);
      window.open(session.auth_link_url, "_blank", "noopener,noreferrer");
      return session;
    },
    onMutate: () => setPending(true),
    onSuccess: () => {
      toast.success("Authorize in the opened tab, then click Refresh");
      queryClient.invalidateQueries({ queryKey: ["sources"] });
    },
    onError: () => toast.error("Failed to start authorization"),
    onSettled: () => setPending(false),
  });

  return (
    <Button variant="outline" size="sm" onClick={() => connect.mutate()} disabled={pending}>
      {pending ? <Loader className="h-3.5 w-3.5 animate-spin mr-1" /> : <Plug className="h-3.5 w-3.5 mr-1" />}
      Connect
    </Button>
  );
}

function DisconnectButton({ bindingId }: { bindingId: string }) {
  const entityId = useAppStore((s) => s.entityId);
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  const disconnect = useMutation({
    mutationFn: async () => {
      await getClient().deleteSource(bindingId, entityId!);
    },
    onMutate: () => setPending(true),
    onSuccess: () => {
      toast.success("Source disconnected");
      queryClient.invalidateQueries({ queryKey: ["sources"] });
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
