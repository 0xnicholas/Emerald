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
    const {
      messages = [],
      model = "gpt-4o-mini",
      memories,
      profile,
    } = body as {
      messages: ChatMessage[];
      model?: string;
      memories?: string;
      profile?: string;
    };

    const apiKey = process.env.OPENAI_API_KEY;

    // C3 无 key 降级：key 存在性是唯一事实源。返回结构化降级标记（D4②），
    // 前端统一消费并显式标识「记忆检索模式」。
    if (!apiKey) {
      const lastUserMsg =
        [...messages].reverse().find((m) => m.role === "user")?.content ?? "";
      const responseText = memories
        ? `AI 回答未启用（服务器未配置 OPENAI_API_KEY）。以下是针对「${lastUserMsg.slice(0, 80)}」检索到的记忆：\n\n${memories}`
        : "AI 回答未启用：服务器未配置 OPENAI_API_KEY。仍可通过搜索栏检索记忆。";
      return new Response(
        JSON.stringify({ degraded: true, content: responseText }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // D5 画像先于记忆注入（引擎原则 5「画像是默认上下文」的 web 落地）。
    // profile 由客户端按 importance 截断后传入（仅静态层，top10 / ~1500 字符）。
    const systemPrompt: ChatMessage = {
      role: "system",
      content: `You are Emerald's memory assistant. You help users understand and work with their personal knowledge base.

## User profile — who they are
${profile || "No profile available yet."}

## Memories relevant to the current conversation
${memories || "No specific memories retrieved."}

Guidelines:
- Ground answers in the user's profile and memories when relevant
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

    // 流式透传（C2 打字机效果的来源）
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
