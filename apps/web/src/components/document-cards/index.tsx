import type { SearchMemory } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type ReactNode } from "react";
import { motion } from "motion/react";
import { Badge } from "@/components/ui/badge";
import { memoryTypeLabel, memoryTypeColor, truncate } from "@/lib/utils";
import { Brain, Quote } from "lucide-react";

interface CardWrapperProps {
  memory: SearchMemory;
  children: ReactNode;
  icon?: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function CardWrapper({ memory, children, icon, onClick, className }: CardWrapperProps) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.15 }}
      className="mb-3 break-inside-avoid"
    >
      <div
        onClick={onClick}
        className={cn(
          "group cursor-pointer rounded-[18px] border border-surface-border bg-surface-card/60 p-3 shadow-[0_12px_40px_rgba(0,0,0,0.22)] backdrop-blur-md transition-all hover:shadow-[0_12px_40px_rgba(0,0,0,0.34)]",
          className
        )}
      >
        {/* Header */}
        <div className="mb-2 flex items-center gap-2">
          {icon && <div className="flex h-6 w-6 items-center justify-center rounded-md bg-surface-hover text-fg-muted shrink-0">{icon}</div>}
          <Badge className={memoryTypeColor(memory.memory_type)}>
            {memoryTypeLabel(memory.memory_type)}
          </Badge>
        </div>

        {children}

        {/* Footer */}
        <div className="mt-2 flex items-center gap-2 border-t border-surface-border/50 pt-2 text-[10px] text-fg-faint">
          {memory.source === "rag" ? "RAG" : "Memory"}
          {memory.score !== undefined && <span>· {Math.round(memory.score * 100)}%</span>}
        </div>
      </div>
    </motion.div>
  );
}

export function NotePreview({ memory, onClick }: { memory: SearchMemory; onClick?: () => void }) {
  return (
    <CardWrapper memory={memory} icon={<Brain className="h-3.5 w-3.5" />} onClick={onClick}>
      <p className="text-xs leading-relaxed text-fg-primary">{truncate(memory.content, 200)}</p>
      {memory.summary && (
        <div className="mt-1.5 flex gap-1 rounded-lg bg-surface-hover/50 p-2">
          <Quote className="mt-0.5 h-3 w-3 shrink-0 text-fg-faint" />
          <p className="text-[10px] italic text-fg-muted">{truncate(memory.summary, 100)}</p>
        </div>
      )}
    </CardWrapper>
  );
}

export function FilePreview({ memory, onClick }: { memory: SearchMemory; onClick?: () => void }) {
  return (
    <CardWrapper memory={memory} icon={<span className="text-xs">📄</span>} onClick={onClick}>
      <div className="flex items-center gap-2 rounded-lg bg-surface-hover/50 p-2">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-card text-xs">📄</div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-fg-primary truncate">{memory.document_title || "Untitled"}</p>
          <p className="text-[10px] text-fg-faint">Uploaded file</p>
        </div>
      </div>
      <p className="mt-1.5 text-xs text-fg-muted line-clamp-2">{truncate(memory.content, 150)}</p>
    </CardWrapper>
  );
}

export function WebsitePreview({ memory, onClick }: { memory: SearchMemory; onClick?: () => void }) {
  return (
    <CardWrapper memory={memory} icon={<span className="text-xs">🌐</span>} onClick={onClick}>
      <div className="flex items-center gap-2">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-hover text-[10px]">🌐</div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-fg-primary truncate">{memory.document_title || "Web Page"}</p>
        </div>
      </div>
      <p className="mt-1.5 text-xs text-fg-muted line-clamp-3">{truncate(memory.content, 180)}</p>
    </CardWrapper>
  );
}

export function YoutubePreview({ memory, onClick }: { memory: SearchMemory; onClick?: () => void }) {
  return (
    <CardWrapper memory={memory} icon={<span className="text-xs">▶️</span>} onClick={onClick}>
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-12 shrink-0 items-center justify-center rounded-lg bg-red-900/30 text-sm">▶️</div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-fg-primary truncate">{memory.document_title || "YouTube Video"}</p>
          <p className="text-[10px] text-fg-faint">YouTube</p>
        </div>
      </div>
      <p className="mt-1.5 text-xs text-fg-muted line-clamp-2">{truncate(memory.content, 120)}</p>
    </CardWrapper>
  );
}
