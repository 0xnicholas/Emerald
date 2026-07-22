"use client";

import { Sidebar } from "@/components/layout/sidebar";
import { DemoBanner } from "@/components/layout/demo-banner";
import { DashboardView } from "@/components/dashboard-view";
import { MobileBottomNav } from "@/components/layout/mobile-bottom-nav";
import { AddMemoryModal } from "@/components/add-memory-modal";
import { useAppStore } from "@/stores/app";
import { ConnectionPanel } from "@/components/layout/connection-panel";
import { useEffect, useState } from "react";

export default function HomePage() {
  const { connected, demoMode, hydrateFromStorage } = useAppStore();

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  if (!connected && !demoMode) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base p-4">
        <ConnectionPanel />
      </div>
    );
  }

  return <AppShell />;
}

function AppShell() {
  const entityId = useAppStore((s) => s.entityId);
  const [addOpen, setAddOpen] = useState(false);

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto pb-16 md:pb-0">
        <DemoBanner />
        <div className="mx-auto w-full max-w-5xl flex-1 p-4 md:p-6">
          <DashboardView entityId={entityId} />
        </div>
      </main>
      <MobileBottomNav onAddMemory={() => setAddOpen(true)} />
      <AddMemoryModal isOpen={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}
