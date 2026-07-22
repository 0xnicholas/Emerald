"use client";

import { useRef, useCallback } from "react";
import { Masonry, useInfiniteLoader } from "masonic";
import type { SearchMemory } from "@/lib/types";
import {
  NotePreview, FilePreview, WebsitePreview, YoutubePreview,
  GoogleDocsPreview, NotionPreview, TweetPreview, MCPPreview,
} from "@/components/document-cards";
import { detectCardType } from "@/components/document-cards/utils";
import { Brain } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

interface MemoriesGridProps {
  memories: SearchMemory[];
  onMemoryClick?: (memory: SearchMemory) => void;
  emptyMessage?: string;
  hasMore?: boolean;
  onLoadMore?: () => void;
}

type GridItem = SearchMemory & { _onClick: () => void };

function CardRenderer({ data }: { data: GridItem }) {
  const type = detectCardType(data);
  switch (type) {
    case "website": return <WebsitePreview memory={data} onClick={data._onClick} />;
    case "youtube": return <YoutubePreview memory={data} onClick={data._onClick} />;
    case "file": return <FilePreview memory={data} onClick={data._onClick} />;
    case "google_docs": return <GoogleDocsPreview memory={data} onClick={data._onClick} />;
    case "notion": return <NotionPreview memory={data} onClick={data._onClick} />;
    case "tweet": return <TweetPreview memory={data} onClick={data._onClick} />;
    case "mcp": return <MCPPreview memory={data} onClick={data._onClick} />;
    default: return <NotePreview memory={data} onClick={data._onClick} />;
  }
}

function GridSkeleton() {
  return (
    <div className="columns-2 gap-3 md:columns-3 lg:columns-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="mb-3 break-inside-avoid">
          <div className="rounded-[18px] border border-surface-border bg-surface-card/60 p-3">
            <Skeleton className="mb-2 h-4 w-20 rounded-full" />
            <Skeleton lines={3} className="h-3" />
            <Skeleton className="mt-2 h-3 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function MemoriesGrid({
  memories,
  onMemoryClick,
  emptyMessage = "No memories yet",
  hasMore = false,
  onLoadMore,
}: MemoriesGridProps) {
  const maybeLoadMore = useInfiniteLoader(
    useCallback(() => { onLoadMore?.(); }, [onLoadMore])
  );

  if (memories.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-fg-subtle">
        <Brain className="mb-3 h-10 w-10 opacity-40" />
        <p className="text-sm font-medium">{emptyMessage}</p>
        <p className="mt-1 text-xs">Add content to Emerald or adjust your search</p>
      </div>
    );
  }

  const items: GridItem[] = memories.map((m) => ({ ...m, _onClick: () => onMemoryClick?.(m) }));

  return (
    <Masonry
      items={items}
      columnGutter={12}
      columnWidth={280}
      overscanBy={2}
      render={CardRenderer}
      onRender={maybeLoadMore}
    />
  );
}

export { GridSkeleton };
