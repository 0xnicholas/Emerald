"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { toast } from "sonner";

interface ConnectorStatus {
  provider: string;
  sync_status: string;
  last_synced_at: string | null;
  error_message: string | null;
  connected_at: string | null;
}

const CONNECTOR_PROVIDERS = [
  "google-drive",
  "notion",
  "github",
  "gmail",
];

export function useConnectors(entityId: string, opts?: { enabled?: boolean }) {
  return useQuery<ConnectorStatus[]>({
    queryKey: ["connectors", entityId],
    queryFn: async () => {
      const statuses: ConnectorStatus[] = [];
      for (const provider of CONNECTOR_PROVIDERS) {
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
    enabled: !!entityId && (opts?.enabled ?? true),
    staleTime: 10_000,
  });
}

export function useDisconnectConnector() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (provider: string) => {
      await getClient().disconnectConnector(provider);
    },
    onSuccess: () => {
      toast.success("Connector disconnected");
      queryClient.invalidateQueries({ queryKey: ["connectors"] });
    },
    onError: () => toast.error("Failed to disconnect connector"),
  });
}
