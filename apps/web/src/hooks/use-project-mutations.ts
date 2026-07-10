"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getClient } from "@/lib/api";
import { useAppStore } from "@/stores/app";
import type { Space } from "@/lib/types";
import { useSelectedSpace, DEFAULT_SPACE_TAG } from "./use-space";

export function useProjectMutations() {
  const queryClient = useQueryClient();
  const entityId = useAppStore((s) => s.entityId);
  const { selectedSpaceTag, setSelectedSpaceTag } = useSelectedSpace();

  const createSpaceMutation = useMutation({
    mutationFn: ({ name, emoji }: { name: string; emoji: string }) =>
      getClient().createSpace(name, emoji, entityId),
    onSuccess: (data) => {
      toast.success("Space created!");
      queryClient.invalidateQueries({ queryKey: ["container-tags"] });
      if (data?.containerTag) {
        setSelectedSpaceTag(data.containerTag);
      }
    },
    onError: (err) => {
      toast.error("Failed to create space", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    },
  });

  const updateSpaceMutation = useMutation({
    mutationFn: ({ tag, name, emoji }: { tag: string; name?: string; emoji?: string }) =>
      getClient().updateSpace(tag, entityId, { name, emoji }),
    onMutate: async ({ tag, name }) => {
      await queryClient.cancelQueries({ queryKey: ["container-tags"] });
      const previous = queryClient.getQueryData<Space[]>(["container-tags"]);
      if (name) {
        queryClient.setQueryData<Space[]>(["container-tags"], (old) =>
          old?.map((s) => (s.containerTag === tag ? { ...s, name: name! } : s))
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["container-tags"], context.previous);
      }
      toast.error("Failed to rename space");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["container-tags"] });
    },
  });

  const deleteSpaceMutation = useMutation({
    mutationFn: ({ tag }: { tag: string }) =>
      getClient().deleteSpace(tag, entityId),
    onSuccess: () => {
      toast.success("Space deleted");
      queryClient.invalidateQueries({ queryKey: ["container-tags"] });
      if (selectedSpaceTag !== DEFAULT_SPACE_TAG) {
        setSelectedSpaceTag(DEFAULT_SPACE_TAG);
      }
    },
    onError: (err) => {
      toast.error("Failed to delete space", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    },
  });

  return { createSpaceMutation, updateSpaceMutation, deleteSpaceMutation };
}
