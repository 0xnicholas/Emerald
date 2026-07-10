"use client";

import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { useAppStore } from "@/stores/app";
import type { Space } from "@/lib/types";

export function useContainerTags() {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);

  const { data: spaces = [], isLoading } = useQuery({
    queryKey: ["container-tags", entityId],
    queryFn: () => getClient().listSpaces(entityId),
    enabled: !!entityId && !demoMode,
    staleTime: 30_000,
  });

  return { spaces: spaces as Space[], isLoading };
}
