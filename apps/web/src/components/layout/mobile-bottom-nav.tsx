"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Search,
  Plus,
  Share2,
  Settings,
  MessageSquare,
  MoreHorizontal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface MobileBottomNavProps {
  onAddMemory?: () => void;
}

export function MobileBottomNav({ onAddMemory }: MobileBottomNavProps) {
  const pathname = usePathname();
  const router = useRouter();
  const setChatOpen = useAppStore((s) => s.setChatOpen);

  const navItems = [
    { href: "/", label: "Home", icon: LayoutDashboard },
    { href: "/memories", label: "Memories", icon: Search },
    { href: "/graph", label: "Graph", icon: Share2 },
  ];

  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-surface-border bg-surface-card/85 shadow-[0_-8px_24px_rgba(0,0,0,0.35)] backdrop-blur-xl md:hidden"
    >
      <div className="flex items-center justify-around px-1 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <button
              key={item.href}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => router.push(item.href)}
              className={cn(
                "flex flex-1 flex-col items-center gap-1 rounded-lg py-1 outline-none transition-colors active:scale-95",
                active ? "text-brand-accent" : "text-fg-muted hover:text-fg-primary"
              )}
            >
              <item.icon className="h-5 w-5" />
              <span className="text-[10px] font-medium leading-none">{item.label}</span>
            </button>
          );
        })}

        {/* Center chat orb */}
        <button
          type="button"
          aria-label="Chat"
          onClick={() => setChatOpen(true)}
          className="group relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full shadow-[0_0_18px_rgba(75,160,250,0.35)] bg-brand-accent outline-none transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-brand-accent/60 active:scale-95"
        >
          <MessageSquare className="h-5 w-5 text-white" />
        </button>

        <button
          type="button"
          aria-current={false}
          onClick={() => onAddMemory?.()}
          className="flex flex-1 flex-col items-center gap-1 rounded-lg py-1 outline-none transition-colors active:scale-95 text-fg-muted hover:text-fg-primary"
        >
          <Plus className="h-5 w-5" />
          <span className="text-[10px] font-medium leading-none">Add</span>
        </button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="More"
              className="flex flex-1 flex-col items-center gap-1 rounded-lg py-1 outline-none transition-colors active:scale-95 text-fg-muted hover:text-fg-primary"
            >
              <MoreHorizontal className="h-5 w-5" />
              <span className="text-[10px] font-medium leading-none">More</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="top"
            align="end"
            sideOffset={12}
            className="min-w-[180px] rounded-2xl border border-surface-border bg-surface-card p-1.5 shadow-[0px_1.5px_20px_0px_rgba(0,0,0,0.65)]"
          >
            <DropdownMenuItem
              onClick={() => router.push("/settings")}
              className="gap-2 rounded-md px-3 py-2.5 text-sm font-medium text-fg-primary hover:bg-surface-hover cursor-pointer"
            >
              <Settings className="h-4 w-4 text-fg-muted" />
              Settings
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => router.push("/integrations")}
              className="gap-2 rounded-md px-3 py-2.5 text-sm font-medium text-fg-primary hover:bg-surface-hover cursor-pointer"
            >
              <Share2 className="h-4 w-4 text-fg-muted" />
              Integrations
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </nav>
  );
}
