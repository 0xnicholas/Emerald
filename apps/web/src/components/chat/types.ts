import type { SearchMemory } from "@/lib/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  relatedMemories?: SearchMemory[];
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
  model: string;
}

let messageCounter = 0;

export function createMessage(
  role: "user" | "assistant",
  content: string,
  relatedMemories?: SearchMemory[]
): ChatMessage {
  messageCounter++;
  return {
    id: `msg_${Date.now()}_${messageCounter}`,
    role,
    content,
    timestamp: new Date(),
    relatedMemories,
  };
}

const DEMO_RESPONSES = [
  "Based on the memories I have, you've been working on Emerald's knowledge graph architecture. You prefer TypeScript and have experience with both frontend and backend development. Would you like to explore specific aspects of the project?",
  "I remember you were researching knowledge graph databases comparing Neo4j and SurrealDB. The key difference is that Neo4j is more mature with better tooling, while SurrealDB offers built-in vector search which could reduce infrastructure complexity.",
  "Your recent focus has been on the payment module microservices refactoring. You mentioned adopting CQRS pattern for the payment system architecture. Would you like me to find the relevant architectural decisions?",
  "I found several memories about your preference for async communication and morning code reviews. Your typical workflow involves deep work in the afternoon after reviewing PRs in the morning.",
];

let demoIdx = 0;

export function getDemoResponse(): string {
  const r = DEMO_RESPONSES[demoIdx % DEMO_RESPONSES.length];
  demoIdx++;
  return r;
}

export const DEMO_SESSIONS: ChatSession[] = [
  {
    id: "session_1",
    title: "Emerald architecture discussion",
    messages: [
      createMessage("user", "What have I been working on recently?"),
      createMessage("assistant", DEMO_RESPONSES[0]),
      createMessage("user", "Tell me about the database choices"),
      createMessage("assistant", DEMO_RESPONSES[1]),
    ],
    createdAt: new Date(Date.now() - 3600000),
    model: "emerald-memory",
  },
  {
    id: "session_2",
    title: "Payment module refactoring",
    messages: [
      createMessage("user", "What was my decision on the payment architecture?"),
      createMessage("assistant", DEMO_RESPONSES[2]),
    ],
    createdAt: new Date(Date.now() - 86400000),
    model: "emerald-memory",
  },
];
