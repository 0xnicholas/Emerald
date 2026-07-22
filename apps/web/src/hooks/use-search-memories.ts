"use client";

import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import type { SearchMemory } from "@/lib/types";

interface SearchOptions {
  searchMode?: "hybrid" | "memory" | "rag";
  topK?: number;
  rerank?: boolean;
  rewriteQuery?: boolean;
  minConfidence?: number;
  filters?: Record<string, unknown>;
  enabled?: boolean;
}

export function useSearchMemories(
  q: string,
  entityId: string,
  opts: SearchOptions = {}
) {
  return useQuery<{ results: SearchMemory[]; search_mode: string }>({
    queryKey: ["search", entityId, q, opts.searchMode ?? "hybrid", opts.topK ?? 50, opts.filters],
    queryFn: () =>
      getClient().search(q, entityId, {
        searchMode: opts.searchMode ?? "hybrid",
        topK: opts.topK ?? 50,
        rerank: opts.rerank,
        rewriteQuery: opts.rewriteQuery,
        minConfidence: opts.minConfidence,
        filters: opts.filters,
      }),
    enabled: !!entityId && (opts.enabled ?? true),
    staleTime: 10_000,
  });
}
