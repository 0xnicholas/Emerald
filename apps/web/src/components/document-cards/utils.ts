import type { SearchMemory } from "@/lib/types";

export type CardType = "website" | "tweet" | "youtube" | "note" | "file" | "google_docs" | "mcp" | "notion";

const typePrefixes: Record<CardType, string[]> = {
  website: ["http", "www."],
  tweet: ["tweet_", "twitter_"],
  youtube: ["youtube_", "yt_"],
  note: ["note_"],
  file: ["file_", "upload_"],
  google_docs: ["gdoc_", "google_doc_"],
  mcp: ["mcp_"],
  notion: ["notion_"],
};

export function detectCardType(memory: SearchMemory): CardType {
  const id = memory.id.toLowerCase();
  const title = (memory.document_title || "").toLowerCase();
  for (const [type, prefixes] of Object.entries(typePrefixes)) {
    for (const prefix of prefixes) {
      if (id.startsWith(prefix) || title.startsWith(prefix)) {
        return type as CardType;
      }
    }
  }
  // Detect by source
  if (memory.source === "rag") return "file";
  return "note";
}

export function getFaviconUrl(url: string): string {
  try {
    const u = new URL(url);
    return `https://www.google.com/s2/favicons?domain=${u.hostname}&sz=32`;
  } catch {
    return "";
  }
}

export function isYouTubeUrl(url: string): boolean {
  return /youtube\.com|youtu\.be/i.test(url);
}
