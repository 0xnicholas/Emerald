import { create } from "zustand";
import type { Profile } from "@/lib/types";

interface AppState {
  // Connection config
  apiKey: string;
  baseUrl: string;
  entityId: string;
  connected: boolean;
  demoMode: boolean;

  // Cached profile
  profile: Profile | null;
  profileLoading: boolean;

  // UI state
  sidebarOpen: boolean;
  chatOpen: boolean;

  // Actions
  setApiKey: (key: string) => void;
  setBaseUrl: (url: string) => void;
  setEntityId: (id: string) => void;
  setConnected: (v: boolean) => void;
  setDemoMode: (v: boolean) => void;
  setProfile: (p: Profile | null) => void;
  setProfileLoading: (v: boolean) => void;
  toggleSidebar: () => void;
  setChatOpen: (v: boolean) => void;
  hydrateFromStorage: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  apiKey: "",
  // H1 同源默认：空串 = 相对路径（经同源 nginx 代理到引擎）；显式填远端地址仍是合法拓扑
  baseUrl: "",
  entityId: "",
  connected: false,
  demoMode: false,
  profile: null,
  profileLoading: false,
  sidebarOpen: true,
  chatOpen: false,

  setApiKey: (key) => {
    localStorage.setItem("emerald_api_key", key);
    set({ apiKey: key });
  },
  setBaseUrl: (url) => {
    localStorage.setItem("emerald_base_url", url);
    set({ baseUrl: url });
  },
  setEntityId: (id) => {
    localStorage.setItem("emerald_entity_id", id);
    set({ entityId: id });
  },
  setConnected: (v) => set({ connected: v }),
  setDemoMode: (v) => set({ demoMode: v }),
  setProfile: (p) => set({ profile: p }),
  setProfileLoading: (v) => set({ profileLoading: v }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setChatOpen: (v) => set({ chatOpen: v }),

  hydrateFromStorage: () => {
    if (typeof window === "undefined") return;
    set({
      apiKey: localStorage.getItem("emerald_api_key") ?? "",
      baseUrl: localStorage.getItem("emerald_base_url") ?? "",
      entityId: localStorage.getItem("emerald_entity_id") ?? "",
    });
  },
}));
