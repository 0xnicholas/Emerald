"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, Loader } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/typography";
import { useProjectMutations } from "@/hooks/use-project-mutations";

const EMOJI_LIST = [
  "📁", "📂", "🗂️", "📚", "📖", "📝", "✏️", "📌",
  "🎯", "🚀", "💡", "⭐", "🔥", "💎", "🎨", "🎵",
  "🏠", "💼", "🛠️", "⚙️", "🔧", "📊", "📈", "💰",
  "🌟", "✨", "🌈", "🌸", "🌿", "🌴", "🐶", "🦊",
  "🦁", "🐼", "🦄", "❤️", "💙", "💚", "💛", "🧡",
];

interface AddSpaceModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AddSpaceModal({ isOpen, onClose }: AddSpaceModalProps) {
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("📁");
  const { createSpaceMutation } = useProjectMutations();

  const handleClose = () => {
    onClose();
    setName("");
    setEmoji("📁");
  };

  const handleCreate = () => {
    if (!name.trim()) return;
    createSpaceMutation.mutate(
      { name: name.trim(), emoji },
      { onSuccess: () => handleClose() }
    );
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={handleClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.15 }}
            className="w-full max-w-md rounded-[18px] border border-surface-border bg-surface-card/80 shadow-lg backdrop-blur-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-surface-border/50 p-4">
              <h2 className="text-lg font-semibold text-fg-primary">Create Space</h2>
              <button onClick={handleClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted hover:bg-surface-hover">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="p-4 space-y-4">
              <div className="flex gap-3 items-center">
                <button
                  type="button"
                  className="flex items-center justify-center w-12 h-12 rounded-xl bg-surface-hover border border-surface-border text-2xl hover:bg-surface-skeleton transition-colors cursor-pointer"
                  title="Pick emoji"
                >
                  {emoji}
                </button>
                <div className="flex-1">
                  <Label>Space name</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="My new space"
                    className="mt-1"
                    onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                  />
                </div>
              </div>

              {/* Emoji picker grid */}
              <div>
                <Label level="3" className="text-fg-faint mb-2 block">Choose an icon</Label>
                <div className="grid grid-cols-8 gap-1">
                  {EMOJI_LIST.map((e) => (
                    <button
                      key={e}
                      type="button"
                      onClick={() => setEmoji(e)}
                      className={`w-9 h-9 flex items-center justify-center rounded-lg text-lg transition-colors hover:bg-surface-hover cursor-pointer ${
                        emoji === e ? "bg-brand-accent-subtle ring-1 ring-brand-accent" : ""
                      }`}
                    >
                      {e}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <Button variant="ghost" onClick={handleClose}>Cancel</Button>
                <Button onClick={handleCreate} disabled={!name.trim() || createSpaceMutation.isPending}>
                  {createSpaceMutation.isPending ? <Loader className="h-4 w-4 animate-spin mr-1" /> : null}
                  Create Space
                </Button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
