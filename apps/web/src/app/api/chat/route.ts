import { NextRequest } from "next/server";

export const runtime = "edge";
export const dynamic = "force-dynamic";

interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

// OpenAI 兼容后端支持（走查记录 §3.2 预告项）：默认行为不变（OpenAI 官方双档），
// 经 OPENAI_BASE_URL / OPENAI_MODELS 环境变量即可接 DeepSeek 等 OpenAI 兼容服务。
function resolveModelConfig() {
  const models = (process.env.OPENAI_MODELS || "gpt-4o-mini,gpt-4o")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const list = models.length ? models : ["gpt-4o-mini"];
  const defaultModel =
    process.env.OPENAI_DEFAULT_MODEL ||
    (list.includes("gpt-4o-mini") ? "gpt-4o-mini" : list[0]);
  const baseUrl = (
    process.env.OPENAI_BASE_URL || "https://api.openai.com/v1"
  ).replace(/\/+$/, "");
  return { models: list, defaultModel, baseUrl };
}

function providerLabel(baseUrl: string): string {
  try {
    const host = new URL(baseUrl).hostname;
    const known: Record<string, string> = {
      "api.openai.com": "OpenAI",
      "api.deepseek.com": "DeepSeek",
    };
    if (host in known) return known[host];
    const seg = host.split(".").filter(Boolean);
    const name = seg.length >= 2 ? seg[seg.length - 2] : host;
    return name.charAt(0).toUpperCase() + name.slice(1);
  } catch {
    return "Custom";
  }
}

// C4：模型选择器的运行时事实源——列表随部署配置下发，避免 standalone 生产构建
// 把模型清单烘死在客户端 bundle 里。
export async function GET() {
  const { models, defaultModel, baseUrl } = resolveModelConfig();
  return new Response(
    JSON.stringify({ models, default: defaultModel, provider: providerLabel(baseUrl) }),
    { headers: { "Content-Type": "application/json" } }
  );
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { messages = [], model, memories, profile } = body as {
      messages: ChatMessage[];
      model?: string;
      memories?: string;
      profile?: string;
    };

    const { defaultModel, baseUrl } = resolveModelConfig();
    const effectiveModel = model || defaultModel;
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

    const response = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: effectiveModel,
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
