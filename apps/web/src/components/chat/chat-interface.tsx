"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Send, Bot, User, Brain, Loader, Sparkles, Search,
  X, ChevronDown, Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { memoryTypeLabel, memoryTypeColor } from "@/lib/utils";
import { getClient } from "@/lib/api";
import { useAppStore } from "@/stores/app";
import { getMockSearchResults } from "@/lib/mock-data";
import {
  createMessage, formatMemoryResponse, readSessions, writeSessions,
  CHAT_MODELS, type ChatMessage, type ChatSession, type ChatModelId, type ChatModel,
} from "./types";
import type { SearchMemory } from "@/lib/types";

interface ChatInterfaceProps {
  onClose?: () => void;
}

const WELCOME_MSG: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content: "I'm your memory assistant. I can search through your saved memories to answer questions about what you've learned, your preferences, and past events. Try asking me something!",
  timestamp: new Date(),
};

// ─── @-mention search ─────────────────────────────────────────────────

function useAtMentionSearch(entityId: string, demoMode: boolean) {
  const [results, setResults] = useState<SearchMemory[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback((q: string) => {
    if (!q.trim()) { setResults([]); setIsOpen(false); return; }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = demoMode
          ? getMockSearchResults(q)
          : await getClient().search(q, entityId, { searchMode: "memory", topK: 6 });
        setResults(data.results.slice(0, 6));
        setIsOpen(true);
      } catch { setResults([]); }
    }, 200);
  }, [entityId, demoMode]);

  const close = useCallback(() => { setIsOpen(false); setResults([]); }, []);
  return { results, isOpen, search, close };
}

// ─── Main Component ───────────────────────────────────────────────────

export function ChatInterface({ onClose }: ChatInterfaceProps) {
  const entityId = useAppStore((s) => s.entityId);
  const demoMode = useAppStore((s) => s.demoMode);

  // Sessions
  const [sessions, setSessions] = useState<ChatSession[]>(() => readSessions());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // Messages
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MSG]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ChatModelId>("gpt-4o-mini");
  const [modelOptions, setModelOptions] = useState<ChatModel[]>(CHAT_MODELS);

  // @-mention
  const atMention = useAtMentionSearch(entityId, demoMode);
  const [showAtMention, setShowAtMention] = useState(false);
  const [atMentionIndex, setAtMentionIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const atTriggerPos = useRef<number>(-1);

  // C4：运行时模型列表（OPENAI_MODELS 经 GET /api/chat 下发）；拉取失败回退内建 OpenAI 双档
  useEffect(() => {
    let cancelled = false;
    fetch("/api/chat")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { models?: string[]; default?: string; provider?: string } | null) => {
        if (cancelled || !data?.models?.length) return;
        const known = new Map(CHAT_MODELS.map((m) => [m.id, m]));
        const options: ChatModel[] = data.models.map((id) =>
          known.get(id) ?? {
            id,
            label: id,
            provider: data.provider ?? "Custom",
            description: "部署配置模型（OPENAI_MODELS）",
          }
        );
        setModelOptions(options);
        setSelectedModel((cur) =>
          options.some((m) => m.id === cur) ? cur : (data.default ?? options[0].id)
        );
      })
      .catch(() => {/* 回退内建列表 */});
    return () => {
      cancelled = true;
    };
  }, []);

  // ─── Effects ─────────────────────────────────────────────────────

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // ─── Session management ──────────────────────────────────────────

  const currentSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) ?? null,
    [sessions, activeSessionId]
  );

  const persistSessions = useCallback((updated: ChatSession[]) => {
    setSessions(updated);
    writeSessions(updated);
  }, []);

  const saveSession = useCallback((msgs: ChatMessage[]) => {
    const title = msgs.find((m) => m.role === "user")?.content.slice(0, 60) || "Chat";
    const session: ChatSession = {
      id: activeSessionId || `session_${Date.now()}`,
      title,
      messages: msgs,
      createdAt: currentSession?.createdAt ?? new Date(),
      updatedAt: new Date(),
      model: selectedModel,
    };
    const updated = [session, ...sessions.filter((s) => s.id !== session.id)];
    persistSessions(updated);
    if (!activeSessionId) setActiveSessionId(session.id);
  }, [activeSessionId, sessions, selectedModel, currentSession, persistSessions]);

  const handleNewChat = useCallback(() => {
    setActiveSessionId(null);
    setMessages([WELCOME_MSG]);
    setInput("");
    setShowAtMention(false);
  }, []);

  const handleLoadSession = useCallback((session: ChatSession) => {
    setActiveSessionId(session.id);
    setMessages(session.messages);
    setShowAtMention(false);
  }, []);

  const handleDeleteSession = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    persistSessions(sessions.filter((s) => s.id !== id));
    if (activeSessionId === id) handleNewChat();
  }, [sessions, activeSessionId, persistSessions, handleNewChat]);

  // ─── Send / Search ──────────────────────────────────────────────

  const handleSend = useCallback(async (q: string) => {
    if (!q.trim() || isLoading) return;
    const userMsg = createMessage("user", q);
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setIsLoading(true);
    setShowAtMention(false);

    try {
      // 1. 检索（hybrid topK 8，现状保留）——与 Sources 面板同源
      const results = demoMode
        ? getMockSearchResults(q).results.slice(0, 8)
        : (await getClient().search(q, entityId, { searchMode: "hybrid", topK: 8 })).results;

      // Demo 模式无后端，保留模板回复
      if (demoMode) {
        await new Promise((r) => setTimeout(r, 300 + Math.random() * 200));
        const { text, memories } = formatMemoryResponse(q, results);
        const final = [...newMessages, createMessage("assistant", text, memories)];
        setMessages(final);
        saveSession(final);
        return;
      }

      // 2. 画像（D5：仅静态层，importance 降序 top10 / ~1500 字符，客户端截断后随请求传入）
      let profileText: string | undefined;
      try {
        const profile = await getClient().getProfile(entityId);
        const facts = [...(profile.static ?? [])]
          .sort((a, b) => (b.importance ?? 0) - (a.importance ?? 0))
          .slice(0, 10)
          .map((f) => `• ${f.content}`);
        profileText = facts.length ? facts.join("\n").slice(0, 1500) : undefined;
      } catch {
        // 画像不可用不阻断对话（P3 尽力而为）
      }

      // 3. 记忆上下文拼入请求（C1：回答须引用检索内容而非模板）
      const memoriesText = results.length
        ? results.map((r) => `• ${r.content}`).join("\n").slice(0, 4000)
        : undefined;

      // 4. 流式占位消息（Sources 面板即到即显）
      const botMsg = createMessage("assistant", "", results);
      setMessages([...newMessages, botMsg]);
      const finalize = (content: string, degraded = false) => {
        const finalMsg = { ...botMsg, content, degraded };
        const final = [...newMessages, finalMsg];
        setMessages(final);
        saveSession(final);
      };

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: newMessages.map(({ role, content }) => ({ role, content })),
          model: selectedModel, // C4：模型选择器真实生效
          memories: memoriesText,
          profile: profileText,
        }),
      });

      if (!res.ok) throw new Error(`Chat API error (${res.status})`);

      const ctype = res.headers.get("content-type") ?? "";
      if (ctype.includes("application/json")) {
        // D4② 结构化降级：route 是 key 存在性的唯一事实源
        const data = await res.json();
        if (data.degraded) {
          finalize(data.content ?? "", true);
        } else {
          throw new Error(data.error ?? "Chat API error");
        }
        return;
      }

      // 5. SSE 流式消费（C2 打字机）
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response stream");
      const decoder = new TextDecoder();
      let buf = "";
      let acc = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          const t = line.trim();
          if (!t.startsWith("data:")) continue;
          const payload = t.slice(5).trim();
          if (payload === "[DONE]") continue;
          try {
            const chunk = JSON.parse(payload);
            const delta: string = chunk.choices?.[0]?.delta?.content ?? "";
            if (delta) {
              acc += delta;
              setMessages([...newMessages, { ...botMsg, content: acc }]);
            }
          } catch {
            // 忽略非 JSON 行
          }
        }
      }
      finalize(acc);
    } catch {
      const errMsg = createMessage("assistant", "Sorry, I encountered an error. Please try again.");
      const final = [...newMessages, errMsg];
      setMessages(final);
    } finally {
      setIsLoading(false);
    }
  }, [messages, isLoading, entityId, demoMode, selectedModel, saveSession]);

  // ─── Input handling ──────────────────────────────────────────────

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setInput(value);

    // @-mention detection
    const cursorPos = e.target.selectionStart ?? value.length;
    const beforeCursor = value.slice(0, cursorPos);
    const atIdx = beforeCursor.lastIndexOf("@");

    if (atIdx >= 0 && (atIdx === 0 || beforeCursor[atIdx - 1] === " ")) {
      const query = beforeCursor.slice(atIdx + 1);
      if (!query.includes(" ")) {
        atTriggerPos.current = atIdx;
        setShowAtMention(true);
        atMention.search(query);
        setAtMentionIndex(0);
        return;
      }
    }
    setShowAtMention(false);
    atMention.close();
  }, [atMention]);

  const handleSelectMention = useCallback((memory: SearchMemory) => {
    if (atTriggerPos.current < 0) return;
    const before = input.slice(0, atTriggerPos.current);
    const after = input.slice(input.indexOf(" ", atTriggerPos.current) >= 0
      ? input.indexOf(" ", atTriggerPos.current)
      : input.length);
    const newInput = before + `@${memory.content.slice(0, 40)}... ` + after;
    setInput(newInput);
    setShowAtMention(false);
    atMention.close();
    inputRef.current?.focus();
  }, [input, atMention]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (showAtMention && atMention.results.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setAtMentionIndex((i) => Math.min(i + 1, atMention.results.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setAtMentionIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        handleSelectMention(atMention.results[atMentionIndex]);
        return;
      }
      if (e.key === "Escape") {
        setShowAtMention(false);
        atMention.close();
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(input.trim());
    }
  }, [showAtMention, atMention, atMentionIndex, handleSelectMention, handleSend, input]);

  // ─── Render ──────────────────────────────────────────────────────

  const currentModelLabel = modelOptions.find((m) => m.id === selectedModel)?.label ?? "Auto";

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
            <Plus className="h-3.5 w-3.5" />
          </Button>
          {onClose && (
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} title="Close">
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* Model selector + Session pills */}
      <div className="flex items-center gap-2 border-b border-surface-border/30 px-3 py-1.5">
        <Popover>
          <PopoverTrigger asChild>
            <button className="flex items-center gap-1 shrink-0 rounded-full px-2.5 py-1 bg-surface-hover hover:bg-surface-border/50 text-[10px] font-medium text-fg-muted transition-colors">
              <Brain className="h-3 w-3" />
              {currentModelLabel}
              <ChevronDown className="h-2.5 w-2.5" />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-56 p-1.5 rounded-2xl border-surface-border bg-surface-card shadow-xl" side="top">
            {modelOptions.map((model) => (
              <button
                key={model.id}
                onClick={() => setSelectedModel(model.id)}
                className={cn(
                  "flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                  selectedModel === model.id
                    ? "bg-brand-accent-subtle text-brand-accent"
                    : "text-fg-primary hover:bg-surface-hover"
                )}
              >
                <div className="flex-1 min-w-0">
                  <p className="font-medium">{model.label}</p>
                  <p className="text-xs text-fg-muted">{model.description}</p>
                </div>
                <Badge className="shrink-0 bg-surface-hover text-fg-faint text-[10px]">
                  {model.provider}
                </Badge>
              </button>
            ))}
          </PopoverContent>
        </Popover>

        {/* Session pills */}
        <div className="flex gap-1.5 overflow-x-auto scrollbar-thin">
          {sessions.slice(0, 4).map((s) => (
            <div key={s.id} className="relative group shrink-0">
              <button
                onClick={() => handleLoadSession(s)}
                className={cn(
                  "px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors whitespace-nowrap max-w-[120px] truncate",
                  activeSessionId === s.id
                    ? "bg-brand-accent-subtle text-brand-accent"
                    : "bg-surface-hover text-fg-muted hover:text-fg-primary"
                )}
              >
                {s.title}
              </button>
              <button
                onClick={(e) => handleDeleteSession(e, s.id)}
                className="absolute -top-1 -right-1 hidden group-hover:flex h-3.5 w-3.5 items-center justify-center rounded-full bg-bg-error text-text-error"
              >
                <X className="h-2 w-2" />
              </button>
            </div>
          ))}
        </div>
      </div>

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
                className={cn("flex gap-3", msg.role === "user" ? "justify-end" : "justify-start")}
              >
                {msg.role === "assistant" && (
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-accent/20">
                    <Bot className="h-3.5 w-3.5 text-brand-accent" />
                  </div>
                )}
                <div className={cn(
                  "max-w-[85%] rounded-[18px] px-4 py-2.5",
                  msg.role === "user"
                    ? "bg-brand-accent text-white"
                    : "border border-surface-border bg-surface-card/60 backdrop-blur-md"
                )}>
                  {/* C3 降级态显式标识 */}
                  {msg.role === "assistant" && msg.degraded && (
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <Badge className="bg-surface-hover text-fg-muted text-[9px]">记忆检索模式</Badge>
                      <span className="text-[9px] text-fg-faint">未配置 AI key</span>
                    </div>
                  )}
                  <div className={cn(
                    "text-sm leading-relaxed whitespace-pre-wrap",
                    msg.role === "user" ? "text-white" : "text-fg-primary"
                  )}>
                    {msg.content}
                  </div>

                  {/* Related memories */}
                  {msg.role === "assistant" && msg.relatedMemories && msg.relatedMemories.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-surface-border/30 space-y-1">
                      <div className="flex items-center gap-1 text-[10px] text-fg-faint">
                        <Brain className="h-3 w-3" />
                        Sources ({msg.relatedMemories.length})
                      </div>
                      {msg.relatedMemories.slice(0, 3).map((mem) => (
                        <div key={mem.id} className="flex items-start gap-1.5 text-[10px] text-fg-muted">
                          <Search className="h-2.5 w-2.5 mt-0.5 shrink-0" />
                          <span className="line-clamp-1">{mem.content}</span>
                          <Badge className={cn(memoryTypeColor(mem.memory_type), "text-[8px] px-1 py-0 shrink-0")}>
                            {memoryTypeLabel(mem.memory_type)}
                          </Badge>
                        </div>
                      ))}
                      {msg.relatedMemories.length > 3 && (
                        <p className="text-[10px] text-fg-faint pl-4">+{msg.relatedMemories.length - 3} more</p>
                      )}
                    </div>
                  )}

                  <p className={cn("mt-1 text-[10px]", msg.role === "user" ? "text-white/60" : "text-fg-faint")}>
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

      {/* @-mention dropdown */}
      <AnimatePresence>
        {showAtMention && atMention.results.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.95 }}
            className="mx-3 border border-surface-border bg-surface-card/95 backdrop-blur-xl rounded-2xl shadow-xl overflow-hidden"
          >
            <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-fg-faint font-medium border-b border-surface-border/30">
              @ Mention — Search memories
            </div>
            <div className="max-h-40 overflow-y-auto p-1">
              {atMention.results.map((mem, i) => (
                <button
                  key={mem.id}
                  onClick={() => handleSelectMention(mem)}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left transition-colors",
                    i === atMentionIndex ? "bg-brand-accent-subtle" : "hover:bg-surface-hover"
                  )}
                >
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-hover text-fg-muted">
                    <Search className="h-3 w-3" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-fg-primary truncate">{mem.content}</p>
                    <div className="flex items-center gap-1 mt-0.5">
                      <Badge className={cn(memoryTypeColor(mem.memory_type), "text-[9px] px-1 py-0")}>
                        {memoryTypeLabel(mem.memory_type)}
                      </Badge>
                      {mem.score !== undefined && (
                        <span className="text-[10px] text-fg-faint">{Math.round(mem.score * 100)}%</span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input */}
      <div className="border-t border-surface-border/50 p-3">
        <div className="relative flex items-center gap-2 rounded-[18px] border border-surface-border bg-surface-card/60 p-1.5 backdrop-blur-md focus-within:border-brand-accent/50 transition-colors">
          <Input
            ref={inputRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your memories... (@ to mention)"
            className="border-0 bg-transparent focus:ring-0 text-sm h-9"
          />
          <Button
            size="icon"
            variant="ghost"
            onClick={() => handleSend(input.trim())}
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
        <p className="mt-1 text-[9px] text-fg-faint text-center">
          Type <kbd className="px-0.5 rounded bg-surface-hover font-mono">@</kbd> to search memories · Press ↑↓ to navigate suggestions
        </p>
      </div>
    </div>
  );
}
