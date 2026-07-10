"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, FileText, Link2, Upload, Send, Loader, CheckCircle2, Globe, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/typography";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { getClient } from "@/lib/api";

interface AddMemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAdd?: (type: string, content: string) => Promise<boolean>;
}

export function AddMemoryModal({ isOpen, onClose, onAdd }: AddMemoryModalProps) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.15 }}
            className="w-full max-w-lg rounded-[18px] border border-surface-border bg-surface-card/80 shadow-[0_12px_40px_rgba(0,0,0,0.34)] backdrop-blur-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-surface-border/50 p-4">
              <h2 className="text-lg font-semibold text-fg-primary">Add Memory</h2>
              <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted hover:bg-surface-hover">
                <X className="h-4 w-4" />
              </button>
            </div>

            <AddMemoryForm onAdd={onAdd} onClose={onClose} />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function AddMemoryForm({ onAdd, onClose }: { onAdd?: (type: string, content: string) => Promise<boolean>; onClose: () => void }) {
  const [note, setNote] = useState("");
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");
  const [urlPreview, setUrlPreview] = useState<{ title: string; description: string; favicon: string; image: string; site_name: string } | null>(null);
  const [extracting, setExtracting] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Extract URL metadata when URL changes
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!url.trim() || !url.includes(".")) {
      setUrlPreview(null);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setExtracting(true);
      try {
        const data = await getClient().extractUrl(url.trim());
        if (data.title || data.description) {
          setUrlPreview(data);
        }
      } catch {
        // Silently fail — preview is optional
      } finally {
        setExtracting(false);
      }
    }, 800);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [url]);

  const handleSubmit = async (type: string, content: string) => {
    if (!content.trim()) return;
    setSubmitting(true);
    try {
      if (onAdd) {
        await onAdd(type, content);
      }
      setSuccess(true);
      setTimeout(() => { onClose(); }, 800);
    } catch {
      toast.error("Failed to save memory");
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <CheckCircle2 className="h-12 w-12 text-text-success mb-3" />
        <p className="text-sm font-medium text-fg-primary">Memory saved!</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <Tabs defaultValue="note">
        <TabsList className="w-full">
          <TabsTrigger value="note" className="flex-1"><FileText className="h-4 w-4 mr-1.5" />Note</TabsTrigger>
          <TabsTrigger value="link" className="flex-1"><Link2 className="h-4 w-4 mr-1.5" />Link</TabsTrigger>
          <TabsTrigger value="file" className="flex-1"><Upload className="h-4 w-4 mr-1.5" />File</TabsTrigger>
        </TabsList>

        <TabsContent value="note" className="mt-4 space-y-3">
          <Label>Write a note or memory</Label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What would you like to remember?"
            rows={5}
            className="w-full rounded-lg border border-surface-border bg-surface-card px-3 py-2 text-sm text-fg-primary placeholder:text-fg-faint focus:outline-none focus:ring-2 focus:ring-surface-ring resize-none"
          />
          <Button onClick={() => handleSubmit("note", note)} disabled={!note.trim() || submitting} className="w-full">
            {submitting ? <Loader className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Save Note
          </Button>
        </TabsContent>

        <TabsContent value="link" className="mt-4 space-y-3">
          <Label>Paste a URL</Label>
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/article"
          />

          {/* URL preview */}
          {extracting && (
            <div className="flex items-center gap-2 rounded-lg bg-surface-hover/50 p-3 text-sm text-fg-muted">
              <Loader className="h-4 w-4 animate-spin" />
              Extracting page info...
            </div>
          )}
          {urlPreview && !extracting && (
            <div className="rounded-xl border border-surface-border bg-surface-card/60 overflow-hidden">
              {urlPreview.image && (
                <div className="h-32 bg-surface-hover overflow-hidden">
                  <img
                    src={urlPreview.image}
                    alt=""
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                </div>
              )}
              <div className="p-3 space-y-1">
                <div className="flex items-center gap-2">
                  {urlPreview.favicon && (
                    <img src={urlPreview.favicon} alt="" className="w-4 h-4 rounded"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                  )}
                  <Globe className="h-3.5 w-3.5 text-fg-faint shrink-0" />
                  <p className="text-xs text-fg-muted truncate">
                    {urlPreview.site_name || new URL(url).hostname}
                  </p>
                </div>
                <p className="text-sm font-medium text-fg-primary line-clamp-2">
                  {urlPreview.title || url}
                </p>
                {urlPreview.description && (
                  <p className="text-xs text-fg-muted line-clamp-2">{urlPreview.description}</p>
                )}
              </div>
            </div>
          )}

          <Button onClick={() => handleSubmit("link", url)} disabled={!url.trim() || submitting} className="w-full">
            {submitting ? <Loader className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
            {urlPreview ? "Save Link" : "Save Link"}
          </Button>
        </TabsContent>

        <TabsContent value="file" className="mt-4 space-y-3">
          <Label>Upload a file</Label>
          <div
            onClick={() => fileRef.current?.click()}
            className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-surface-border p-8 hover:border-brand-accent/50 transition-colors"
          >
            <Upload className="mb-2 h-8 w-8 text-fg-faint" />
            <p className="text-sm text-fg-muted">{fileName || "Click to select a file"}</p>
            <p className="text-xs text-fg-faint">PDF, images, audio, video, code files</p>
          </div>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) setFileName(f.name);
            }}
          />
          <Button onClick={() => handleSubmit("file", fileName)} disabled={!fileName || submitting} className="w-full">
            {submitting ? <Loader className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Upload File
          </Button>
        </TabsContent>
      </Tabs>
    </div>
  );
}
