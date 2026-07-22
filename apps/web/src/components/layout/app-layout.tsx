"use client";

import { ReactNode } from "react";
import { Sidebar } from "@/components/layout/sidebar";
import { DemoBanner } from "@/components/layout/demo-banner";
import { MobileBottomNav } from "@/components/layout/mobile-bottom-nav";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { AddMemoryModal } from "@/components/add-memory-modal";
import { useState } from "react";

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const { connected, demoMode, hydrateFromStorage } = useAppStore();
  const [addOpen, setAddOpen] = useState(false);

  // Hydrate on first render
  // (each page currently does this - this could be moved here, but keeping compat)
  
  if (typeof window !== "undefined" && !connected && !demoMode) {
    // Check localStorage directly for hydration edge case
    const storedConnected = localStorage.getItem("emerald_api_key") ? true : false;
    if (!storedConnected) {
      // Will be handled by individual pages
    }
  }

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto pb-16 md:pb-0">
        <DemoBanner />
        <div className="mx-auto w-full max-w-5xl flex-1 p-4 md:p-6">
          {children}
        </div>
      </main>
      <MobileBottomNav onAddMemory={() => setAddOpen(true)} />
      <AddMemoryModal isOpen={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}

export function LoadingShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col pb-16 md:pb-0">
        <DemoBanner />
        {children}
      </main>
      <MobileBottomNav />
    </div>
  );
}
