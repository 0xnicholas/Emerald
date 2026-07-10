"use client";

import { useState } from "react";
import { ChevronDown, Loader } from "lucide-react";
import { useSelectedSpace } from "@/hooks/use-space";
import { useContainerTags } from "@/hooks/use-container-tags";
import { getSpaceLabel } from "@/lib/spaces";
import { SpaceGlyph } from "./space-glyph";
import { SelectSpacesModal } from "./select-spaces-modal";

export function SpaceSelector() {
  const [modalOpen, setModalOpen] = useState(false);
  const { selectedSpaceTag } = useSelectedSpace();
  const { spaces, isLoading } = useContainerTags();

  const space = spaces.find((s) => s.containerTag === selectedSpaceTag);
  const label = space?.name ?? getSpaceLabel(spaces, selectedSpaceTag);
  const emoji = space?.emoji ?? "📁";

  return (
    <>
      <button
        onClick={() => setModalOpen(true)}
        className="flex items-center gap-2 w-full px-3 py-2 rounded-xl bg-surface-hover/50 border border-surface-border/50 hover:bg-surface-hover hover:border-surface-border transition-all text-left cursor-pointer"
        disabled={isLoading}
      >
        {isLoading ? (
          <Loader className="h-4 w-4 animate-spin text-fg-muted shrink-0" />
        ) : (
          <SpaceGlyph emoji={emoji} size={18} />
        )}
        <span className="flex-1 min-w-0 text-sm font-medium text-fg-primary truncate">
          {isLoading ? "Loading..." : label}
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-fg-faint shrink-0" />
      </button>

      <SelectSpacesModal isOpen={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
