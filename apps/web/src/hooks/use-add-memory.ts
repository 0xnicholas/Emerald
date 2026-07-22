"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { toast } from "sonner";

interface AddMemoryInput {
  content: string;
  entityId: string;
  contentType?: string;
  memoryType?: string;
  confidence?: number;
}

export function useAddMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ content, entityId, contentType, memoryType, confidence }: AddMemoryInput) => {
      return getClient().addMemory(content, entityId, {
        contentType,
        memoryType,
        confidence,
      });
    },
    onSuccess: (_, variables) => {
      toast.success("Memory saved!");
      queryClient.invalidateQueries({ queryKey: ["search"] });
      queryClient.invalidateQueries({ queryKey: ["profile", variables.entityId] });
    },
    onError: () => {
      toast.error("Failed to save memory");
    },
  });
}
