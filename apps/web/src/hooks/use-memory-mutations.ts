"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getClient } from "@/lib/api";

export function useMemoryMutations(entityId: string) {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["search-demo", entityId] });
    queryClient.invalidateQueries({ queryKey: ["search", entityId] });
    queryClient.invalidateQueries({ queryKey: ["profile", entityId] });
  };

  const updateMemoryMutation = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: {
        content?: string;
        summary?: string;
        memory_type?: string;
        confidence?: number;
      };
    }) => getClient().updateMemory(id, data),
    onSuccess: () => {
      toast.success("Memory updated");
      invalidate();
    },
    onError: (err) => {
      toast.error("Failed to update memory", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    },
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: (id: string) => getClient().deleteMemory(id),
    onSuccess: () => {
      toast.success("Memory deleted");
      invalidate();
    },
    onError: (err) => {
      toast.error("Failed to delete memory", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    },
  });

  return { updateMemoryMutation, deleteMemoryMutation };
}
