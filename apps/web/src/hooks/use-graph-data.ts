"use client";

import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import type { GraphNode, GraphEdge } from "@/lib/types";

export function useGraphData(
  entityId: string,
  limit = 150,
  opts?: { enabled?: boolean }
) {
  return useQuery<{ nodes: GraphNode[]; edges: GraphEdge[] }>({
    queryKey: ["graph", entityId, limit],
    queryFn: () => getClient().getGraph(entityId, limit),
    enabled: !!entityId && (opts?.enabled ?? true),
    staleTime: 30_000,
  });
}
