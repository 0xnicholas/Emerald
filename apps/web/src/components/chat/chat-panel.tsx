"use client";

import { useAppStore } from "@/stores/app";
import { ChatInterface } from "@/components/chat/chat-interface";
import { motion, AnimatePresence } from "motion/react";
import { X } from "lucide-react";

export function ChatPanel() {
  const chatOpen = useAppStore((s) => s.chatOpen);
  const setChatOpen = useAppStore((s) => s.setChatOpen);

  return (
    <AnimatePresence>
      {chatOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
            onClick={() => setChatOpen(false)}
          />

          {/* Panel */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-surface-border bg-surface-base shadow-[0_0_60px_rgba(0,0,0,0.3)]"
          >
            <ChatInterface onClose={() => setChatOpen(false)} />
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
