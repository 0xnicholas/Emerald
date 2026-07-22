import { NextRequest } from "next/server";

export const runtime = "edge";
export const dynamic = "force-dynamic";

interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { messages = [], model = "gpt-4o-mini", memories } = body as {
      messages: ChatMessage[];
      model?: string;
      memories?: string;
    };

    const apiKey = process.env.OPENAI_API_KEY;

    // Without API key, return fallback with memory results
    if (!apiKey) {
      const lastUserMsg = [...messages].reverse().find((m) => m.role === "user")?.content ?? "";
      const responseText = memories
        ? `Based on your memories, here's what I found relevant to "${lastUserMsg.slice(0, 80)}":\n\n${memories}`
        : "AI responses require an OPENAI_API_KEY. Set it in your .env file to enable AI-powered chat. For now, I can still search your memories via the search bar.";

      return new Response(
        JSON.stringify({ choices: [{ message: { role: "assistant", content: responseText } }] }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // Build the OpenAI request
    const systemPrompt: ChatMessage = {
      role: "system",
      content: `You are Emerald's memory assistant. You help users understand and work with their personal knowledge base.

The following memories are relevant to the current conversation:
${memories || "No specific memories retrieved."}

Guidelines:
- Answer questions based on the user's memories when relevant
- If you don't know something, say so
- Use natural language — don't list raw memory data
- Be concise but helpful`,
    };

    const openaiMessages = [systemPrompt, ...messages];

    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: openaiMessages,
        temperature: 0.7,
        max_tokens: 1024,
        stream: true,
      }),
    });

    if (!response.ok) {
      const errText = await response.text();
      console.error("[Chat API] OpenAI error:", response.status, errText);
      return new Response(
        JSON.stringify({ error: `OpenAI API error: ${response.status}` }),
        { status: 502, headers: { "Content-Type": "application/json" } }
      );
    }

    // Stream the response
    return new Response(response.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  } catch (error) {
    console.error("[Chat API]", error);
    return new Response(
      JSON.stringify({ error: "Internal server error" }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
}
