"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Search,
  Share2,
  Settings,
  PanelLeftClose,
  PanelLeft,
  Brain,
  MessageSquare,
  Plug,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import { Button } from "@/components/ui/button";
import { SpaceSelector } from "@/components/spaces/space-selector";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/memories", label: "记忆浏览", icon: Search },
  { href: "/graph", label: "知识图谱", icon: Share2 },
  { href: "/integrations", label: "集成", icon: Plug },
  { href: "/settings", label: "设置", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const setChatOpen = useAppStore((s) => s.setChatOpen);

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-surface-border bg-surface-base transition-all duration-200",
        sidebarOpen ? "w-56" : "w-14"
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-surface-border px-3">
        <Brain className="h-6 w-6 shrink-0 text-brand-accent" />
        {sidebarOpen && (
          <span className="text-sm font-semibold tracking-tight text-fg-primary">
            Emerald
          </span>
        )}
      </div>

      {/* Space selector */}
      {sidebarOpen && (
        <div className="px-3 py-2 border-b border-surface-border/50">
          <SpaceSelector />
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 space-y-1 p-2">
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-brand-accent-subtle text-brand-accent"
                  : "text-fg-muted hover:bg-surface-hover hover:text-fg-primary"
              )}
            >
              <item.icon className="h-5 w-5 shrink-0" />
              {sidebarOpen && <span>{item.label}</span>}
            </Link>
          );
        })}

        {/* Chat button */}
        <button
          onClick={() => setChatOpen(true)}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg-primary"
        >
          <MessageSquare className="h-5 w-5 shrink-0" />
          {sidebarOpen && <span>Memory Chat</span>}
        </button>
      </nav>

      {/* Keyboard shortcut hints */}
      {sidebarOpen && (
        <div className="px-3 py-2 border-t border-surface-border/50">
          <div className="flex items-center gap-2 text-[10px] text-fg-faint">
            <kbd className="px-1.5 py-0.5 rounded bg-surface-hover border border-surface-border/50 font-mono text-[9px]">⌘K</kbd>
            <span>Command palette</span>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-fg-faint mt-1">
            <kbd className="px-1.5 py-0.5 rounded bg-surface-hover border border-surface-border/50 font-mono text-[9px]">C</kbd>
            <span>Add memory</span>
          </div>
        </div>
      )}

      {/* Toggle */}
      <div className="border-t border-surface-border p-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="w-full"
          title={sidebarOpen ? "收起侧边栏" : "展开侧边栏"}
        >
          {sidebarOpen ? (
            <PanelLeftClose className="h-4 w-4" />
          ) : (
            <PanelLeft className="h-4 w-4" />
          )}
        </Button>
      </div>
    </aside>
  );
}
