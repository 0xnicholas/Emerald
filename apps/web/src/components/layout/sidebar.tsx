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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import { Button } from "@/components/ui/button";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/memories", label: "记忆浏览", icon: Search },
  { href: "/graph", label: "知识图谱", icon: Share2 },
  { href: "/settings", label: "设置", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-950 transition-all duration-200",
        sidebarOpen ? "w-56" : "w-14"
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-zinc-200 px-3 dark:border-zinc-700">
        <Brain className="h-6 w-6 shrink-0 text-emerald-600" />
        {sidebarOpen && (
          <span className="text-sm font-semibold tracking-tight">Emerald</span>
        )}
      </div>

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
                  ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-200"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              )}
            >
              <item.icon className="h-5 w-5 shrink-0" />
              {sidebarOpen && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Toggle */}
      <div className="border-t border-zinc-200 p-2 dark:border-zinc-700">
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
