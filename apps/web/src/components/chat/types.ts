import type { SearchMemory } from "@/lib/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  relatedMemories?: SearchMemory[];
  reasoning?: string; // Chain of thought / reasoning text
  degraded?: boolean; // C3：无 AI key 的降级回复（记忆检索模式）
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
  model?: string;
}

// D4①：默认列表 = OpenAI 官方双档（claude-sonnet-4 与 auto 已移除，见下）。接 OpenAI 兼容后端
// （OPENAI_BASE_URL，如 DeepSeek）时，运行时列表由 GET /api/chat 下发（OPENAI_MODELS），
// 本表仅作内建档位的元数据与拉取失败时的回退。
export type ChatModelId = string;

export interface ChatModel {
  id: ChatModelId;
  label: string;
  provider: string;
  description: string;
}

export const CHAT_MODELS: ChatModel[] = [
  { id: "gpt-4o-mini", label: "GPT-4o Mini", provider: "OpenAI", description: "Fast, cost-effective" },
  { id: "gpt-4o", label: "GPT-4o", provider: "OpenAI", description: "Best quality, slower" },
];

let messageCounter = 0;

export function createMessage(
  role: "user" | "assistant" | "system",
  content: string,
  relatedMemories?: SearchMemory[],
  reasoning?: string,
  degraded?: boolean,
): ChatMessage {
  messageCounter++;
  return {
    id: `msg_${Date.now()}_${messageCounter}`,
    role,
    content,
    timestamp: new Date(),
    relatedMemories,
    reasoning,
    degraded,
  };
}

export function formatMemoryResponse(
  query: string,
  results: SearchMemory[]
): { text: string; memories: SearchMemory[] } {
  if (results.length === 0) {
    return {
      text: "I couldn't find any relevant memories for that query. Try asking about something else, or add more information to your knowledge base.",
      memories: [],
    };
  }

  const facts = results.filter((r) => r.memory_type === "fact").slice(0, 3);
  const preferences = results.filter((r) => r.memory_type === "preference").slice(0, 2);
  const episodes = results.filter((r) => r.memory_type === "episodic").slice(0, 2);

  const parts: string[] = [];
  if (facts.length > 0) {
    parts.push("Here's what I found:");
    parts.push(facts.map((r) => `• ${r.content}`).join("\n"));
  }
  if (preferences.length > 0) {
    parts.push("\nRegarding your preferences:");
    parts.push(preferences.map((r) => `• ${r.content}`).join("\n"));
  }
  if (episodes.length > 0) {
    parts.push("\nRelevant past events:");
    parts.push(episodes.map((r) => `• ${r.summary || r.content}`).join("\n"));
  }

  if (facts.length + preferences.length + episodes.length < results.length) {
    const remaining = results.length - facts.length - preferences.length - episodes.length;
    parts.push(`\n_+${remaining} more related memories_`);
  }

  return {
    text: parts.join("\n\n"),
    memories: results.slice(0, 8),
  };
}

const SESSIONS_KEY = "emerald:chat-sessions";

export function readSessions(): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

export function writeSessions(sessions: ChatSession[]) {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  } catch { /* noop */ }
}
