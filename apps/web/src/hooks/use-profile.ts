"use client";

import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import type { Profile } from "@/lib/types";

export function useProfile(entityId: string, opts?: { enabled?: boolean }) {
  return useQuery<Profile>({
    queryKey: ["profile", entityId],
    queryFn: () => getClient().getProfile(entityId),
    enabled: !!entityId && (opts?.enabled ?? true),
    staleTime: 30_000,
  });
}
