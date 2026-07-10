"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Send, Bot, User, Brain, Loader, Sparkles, Search, MessageSquare,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { getClient } from "@/lib/api";
import { useAppStore } from "@/stores/app";
import { getMockSearchResults } from "@/lib/mock-data";
import {
  createMessage, formatMemoryResponse,
  type ChatMessage, type ChatSession,
} from "./types";
import type { SearchMemory } from "@/lib/types";

interface ChatInterfaceProps {
  onClose?: () => void;
}

const SESSIONS_KEY = "emerald:chat-sessions";

function readSessions(): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveSessions(sessions: ChatSession[]) {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  } catch { /* noop */ }
}

const WELCOME = "I'm your memory assistant. I can search through your saved memories to answer questions about what you've learned, your preferences, and past events. Try asking me something!";

export function ChatInterface({ onClose }: ChatInterfaceProps) {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);

  const [sessions, setSessions] = useState<ChatSession[]>(readSessions);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    createMessage("assistant", WELCOME),
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [activeSession]);

  const saveCurrentSession = useCallback((msgs: ChatMessage[]) => {
    const title = msgs.find((m) => m.role === "user")?.content.slice(0, 60) || "Chat";
    const session: ChatSession = {
      id: activeSession || `session_${Date.now()}`,
      title,
      messages: msgs,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    const updated = [session, ...sessions.filter((s) => s.id !== session.id)];
    setSessions(updated);
    saveSessions(updated);
    if (!activeSession) setActiveSession(session.id);
  }, [activeSession, sessions]);

  const handleSend = useCallback(async () => {
    if (!input.trim() || isLoading) return;
    const q = input.trim();

    const userMsg = createMessage("user", q);
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setIsLoading(true);

    try {
      // Search memories
      let results: SearchMemory[];
      if (demoMode) {
        const data = getMockSearchResults(q);
        results = data.results.slice(0, 8);
      } else {
        const data = await getClient().search(q, entityId, {
          searchMode: "hybrid",
          topK: 8,
        });
        results = data.results;
      }

      await new Promise((r) => setTimeout(r, 300 + Math.random() * 200));

      const { text, memories } = formatMemoryResponse(q, results);
      const botMsg = createMessage("assistant", text, memories);
      const finalMessages = [...newMessages, botMsg];
      setMessages(finalMessages);
      saveCurrentSession(finalMessages);
    } catch {
      const errorMsg = createMessage("assistant", "Sorry, I encountered an error searching your memories. Please try again.");
      const finalMessages = [...newMessages, errorMsg];
      setMessages(finalMessages);
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, messages, entityId, demoMode, saveCurrentSession]);

  const handleNewChat = useCallback(() => {
    setActiveSession(null);
    setMessages([createMessage("assistant", WELCOME)]);
  }, []);

  const loadSession = useCallback((session: ChatSession) => {
    setActiveSession(session.id);
    setMessages(session.messages);
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border/50 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-accent/20">
            <Sparkles className="h-4 w-4 text-brand-accent" />
          </div>
          <div>
            <p className="text-sm font-medium text-fg-primary">Memory Chat</p>
            <p className="text-[10px] text-fg-faint">Ask about your memories</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleNewChat} title="New chat">
            <MessageSquare className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Sessions list (collapsed) */}
      {sessions.length > 0 && (
        <div className="border-b border-surface-border/30 px-3 py-1.5 flex gap-1.5 overflow-x-auto scrollbar-thin">
          {sessions.slice(0, 5).map((s) => (
            <button
              key={s.id}
              onClick={() => loadSession(s)}
              className={cn(
                "shrink-0 px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors whitespace-nowrap",
                activeSession === s.id
                  ? "bg-brand-accent-subtle text-brand-accent"
                  : "bg-surface-hover text-fg-muted hover:text-fg-primary"
              )}
            >
              {s.title.slice(0, 24)}{s.title.length > 24 ? "…" : ""}
            </button>
          ))}
        </div>
      )}

      {/* Messages */}
      <ScrollArea ref={scrollRef} className="flex-1">
        <div className="space-y-3 p-4">
          <AnimatePresence initial={false}>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2 }}
                className={cn(
                  "flex gap-3",
                  msg.role === "user" ? "justify-end" : "justify-start"
                )}
              >
                {msg.role === "assistant" && (
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-accent/20">
                    <Bot className="h-3.5 w-3.5 text-brand-accent" />
                  </div>
                )}
                <div
                  className={cn(
                    "max-w-[85%] rounded-[18px] px-4 py-2.5",
                    msg.role === "user"
                      ? "bg-brand-accent text-white"
                      : "border border-surface-border bg-surface-card/60 backdrop-blur-md"
                  )}
                >
                  <div className={cn(
                    "text-sm leading-relaxed whitespace-pre-wrap",
                    msg.role === "user" ? "text-white" : "text-fg-primary"
                  )}>
                    {msg.content}
                  </div>

                  {/* Related memories citations */}
                  {msg.role === "assistant" && msg.relatedMemories && msg.relatedMemories.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-surface-border/30 space-y-1">
                      <div className="flex items-center gap-1 text-[10px] text-fg-faint">
                        <Brain className="h-3 w-3" />
                        Sources
                      </div>
                      {msg.relatedMemories.slice(0, 3).map((mem) => (
                        <div key={mem.id} className="flex items-start gap-1.5 text-[10px] text-fg-muted">
                          <Search className="h-2.5 w-2.5 mt-0.5 shrink-0" />
                          <span className="line-clamp-1">{mem.content}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <p className={cn(
                    "mt-1 text-[10px]",
                    msg.role === "user" ? "text-white/60" : "text-fg-faint"
                  )}>
                    {new Date(msg.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
                {msg.role === "user" && (
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-hover">
                    <User className="h-3.5 w-3.5 text-fg-muted" />
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>

          {isLoading && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3"
            >
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-accent/20">
                <Bot className="h-3.5 w-3.5 text-brand-accent" />
              </div>
              <div className="flex items-center gap-1.5 rounded-[18px] border border-surface-border bg-surface-card/60 px-4 py-2.5 backdrop-blur-md">
                <Loader className="h-3.5 w-3.5 animate-spin text-brand-accent" />
                <span className="text-xs text-fg-muted">Searching memories...</span>
              </div>
            </motion.div>
          )}
        </div>
      </ScrollArea>

      {/* Input */}
      <div className="border-t border-surface-border/50 p-3">
        <div className="flex items-center gap-2 rounded-[18px] border border-surface-border bg-surface-card/60 p-1.5 backdrop-blur-md focus-within:border-brand-accent/50 transition-colors">
          <Input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your memories..."
            className="border-0 bg-transparent focus:ring-0 text-sm h-9"
          />
          <Button
            size="icon"
            variant="ghost"
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="h-8 w-8 shrink-0 rounded-xl"
          >
            {isLoading ? (
              <Loader className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
