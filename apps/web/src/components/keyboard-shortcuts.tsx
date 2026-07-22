"use client";

import { useEffect, useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useAppStore } from "@/stores/app";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/typography";
import {
  Command, MessageSquare, Search, Share2, Plus, LayoutDashboard,
  Slash,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ShortcutDef {
  key: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  ctrl?: boolean;
}

const SHORTCUTS: ShortcutDef[] = [
  { key: "k", label: "⌘K", description: "Command palette", icon: <Command className="h-3.5 w-3.5" />, ctrl: true },
  { key: "c", label: "C", description: "Add memory", icon: <Plus className="h-3.5 w-3.5" /> },
  { key: "m", label: "M", description: "Go to Memories", icon: <Search className="h-3.5 w-3.5" /> },
  { key: "g", label: "G", description: "Go to Graph", icon: <Share2 className="h-3.5 w-3.5" /> },
  { key: "d", label: "D", description: "Go to Dashboard", icon: <LayoutDashboard className="h-3.5 w-3.5" /> },
  { key: "t", label: "T", description: "Open Chat", icon: <MessageSquare className="h-3.5 w-3.5" /> },
  { key: "/", label: "/", description: "Focus search", icon: <Search className="h-3.5 w-3.5" /> },
  { key: "?", label: "?", description: "Show shortcuts", icon: <Slash className="h-3.5 w-3.5" /> },
];

export function KeyboardShortcutsProvider() {
  const router = useRouter();
  const setChatOpen = useAppStore((s) => s.setChatOpen);
  const [helpOpen, setHelpOpen] = useState(false);

  const handler = useCallback(
    (e: KeyboardEvent) => {
      // Don't trigger in input fields
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        // Allow ? and Escape in inputs
        if (e.key !== "?" && e.key !== "Escape") return;
      }

      // ⌘K is handled by CommandPaletteProvider
      if ((e.metaKey || e.ctrlKey) && e.key === "k") return;

      // Single-key shortcuts (not in input fields)
      if (!(e.metaKey || e.ctrlKey) && target.tagName !== "INPUT" && target.tagName !== "TEXTAREA") {
        switch (e.key.toLowerCase()) {
          case "c":
            e.preventDefault();
            router.push("/?add=note");
            break;
          case "m":
            e.preventDefault();
            router.push("/memories");
            break;
          case "g":
            e.preventDefault();
            router.push("/graph");
            break;
          case "d":
            e.preventDefault();
            router.push("/");
            break;
          case "t":
            e.preventDefault();
            setChatOpen(true);
            break;
          case "/":
            e.preventDefault();
            // Focus first search input on the page
            const searchInput = document.querySelector<HTMLInputElement>(
              'input[type="text"], input[placeholder*="search" i], input[placeholder*="搜索" i]'
            );
            searchInput?.focus();
            break;
          case "?":
            e.preventDefault();
            setHelpOpen((prev) => !prev);
            break;
        }
      }
    },
    [router, setChatOpen]
  );

  useEffect(() => {
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handler]);

  return (
    <>
      {/* Help dialog */}
      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent className="sm:max-w-[420px] rounded-[18px] border-surface-border bg-surface-card/95 backdrop-blur-xl">
          <DialogTitle className="sr-only">Keyboard Shortcuts</DialogTitle>
          <div className="space-y-1">
            <Label level="2" weight="bold" className="text-fg-primary">
              Keyboard Shortcuts
            </Label>
            <p className="text-xs text-fg-muted">
              Press <kbd className="px-1 py-0.5 rounded bg-surface-hover text-[10px] font-mono border border-surface-border/50">?</kbd> to toggle this panel
            </p>
          </div>
          <div className="space-y-0.5 mt-2">
            {SHORTCUTS.map((s) => (
              <div
                key={s.key}
                className="flex items-center justify-between rounded-lg px-2.5 py-2 hover:bg-surface-hover/50"
              >
                <div className="flex items-center gap-2">
                  <span className="text-fg-muted">{s.icon}</span>
                  <span className="text-sm text-fg-primary">{s.description}</span>
                </div>
                <kbd className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-md bg-surface-hover text-[10px] font-mono text-fg-faint border border-surface-border/50">
                  {s.ctrl && <span className="text-[9px]">⌘</span>}
                  <span>{s.key.toUpperCase()}</span>
                </kbd>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
