"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Send, Bot, User, Brain, Loader, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/typography";
import { cn } from "@/lib/utils";
import { createMessage, getDemoResponse, type ChatMessage } from "./types";

interface ChatInterfaceProps {
  onClose?: () => void;
}

export function ChatInterface({ onClose }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    createMessage("assistant", "Hello! I'm your memory assistant. Ask me anything about what I know about you and your projects."),
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
  }, []);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMsg = createMessage("user", input.trim());
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    // Simulate AI response delay
    await new Promise((r) => setTimeout(r, 800 + Math.random() * 1200));

    const response = getDemoResponse();
    const botMsg = createMessage("assistant", response);
    setMessages((prev) => [...prev, botMsg]);
    setIsLoading(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

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
                    "max-w-[80%] rounded-[18px] px-4 py-2.5",
                    msg.role === "user"
                      ? "bg-brand-accent text-white"
                      : "border border-surface-border bg-surface-card/60 backdrop-blur-md"
                  )}
                >
                  <p className={cn(
                    "text-sm leading-relaxed",
                    msg.role === "user" ? "text-white" : "text-fg-primary"
                  )}>
                    {msg.content}
                  </p>
                  <p className={cn(
                    "mt-1 text-[10px]",
                    msg.role === "user" ? "text-white/60" : "text-fg-faint"
                  )}>
                    {msg.timestamp.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
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
                <span className="text-xs text-fg-muted">Thinking...</span>
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
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
