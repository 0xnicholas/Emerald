import type {
  AddMemoryResult,
  EmeraldConfig,
  Memory,
  PipelineStatus,
  Profile,
  SearchMemory,
  Space,
} from "./types";

export class EmeraldApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown
  ) {
    super(message);
    this.name = "EmeraldApiError";
  }
}

export class EmeraldClient {
  private config: EmeraldConfig;
  private timeout: number;

  constructor(config: EmeraldConfig, timeoutMs = 10_000) {
    this.config = config;
    this.timeout = timeoutMs;
  }

  private get headers(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.config.apiKey}`,
      "Content-Type": "application/json",
    };
  }

  private get baseUrl(): string {
    return this.config.baseUrl.replace(/\/+$/, "");
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let res: Response;
    try {
      res = await fetch(url, {
        method,
        headers: this.headers,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timer);
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new EmeraldApiError(0, "TIMEOUT", `请求超时 (${this.timeout}ms)`);
      }
      throw new EmeraldApiError(0, "NETWORK_ERROR", `网络错误: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      clearTimeout(timer);
    }

    if (!res.ok) {
      let errBody: Record<string, unknown> | undefined;
      try {
        errBody = await res.json();
      } catch {
        // ignore
      }
      throw new EmeraldApiError(
        res.status,
        (errBody?.error_code as string) ?? "UNKNOWN",
        (errBody?.message as string) ?? res.statusText,
        errBody?.details
      );
    }

    const json = await res.json();
    return json as T;
  }

  // ─── Search ───────────────────────────────────────────────────────

  async search(
    q: string,
    entityId: string,
    opts?: {
      searchMode?: "hybrid" | "memory" | "rag";
      topK?: number;
      rerank?: boolean;
      rewriteQuery?: boolean;
      minConfidence?: number;
      filters?: Record<string, unknown>;
    }
  ): Promise<{ results: SearchMemory[]; search_mode: string }> {
    const data = await this.request<{
      data: { results: SearchMemory[]; search_mode: string };
    }>("POST", "/v1/search", {
      q,
      entity_id: entityId,
      search_mode: opts?.searchMode ?? "hybrid",
      top_k: opts?.topK ?? 50,
      rerank: opts?.rerank ?? false,
      rewrite_query: opts?.rewriteQuery ?? false,
      min_confidence: opts?.minConfidence,
      filters: opts?.filters,
    });
    return data.data;
  }

  // ─── Memories ─────────────────────────────────────────────────────

  async getMemory(id: string): Promise<Memory> {
    const data = await this.request<{ data: Memory }>(
      "GET",
      `/v1/memories/${encodeURIComponent(id)}`
    );
    return data.data;
  }

  async addMemory(
    content: string,
    entityId: string,
    opts?: {
      contentType?: string;
      memoryType?: string;
      confidence?: number;
    }
  ): Promise<AddMemoryResult> {
    const data = await this.request<{ data: AddMemoryResult }>(
      "POST",
      "/v1/memories",
      {
        content,
        entity_id: entityId,
        content_type: opts?.contentType ?? "text",
        memory_type: opts?.memoryType,
        confidence: opts?.confidence,
      }
    );
    return data.data;
  }

  async updateMemory(
    id: string,
    data: { content?: string; summary?: string; memory_type?: string; confidence?: number }
  ): Promise<void> {
    await this.request("PATCH", `/v1/memories/${encodeURIComponent(id)}`, data);
  }

  async deleteMemory(id: string): Promise<void> {
    await this.request("DELETE", `/v1/memories/${encodeURIComponent(id)}`);
  }

  // ─── Profile ──────────────────────────────────────────────────────

  async getProfile(entityId: string): Promise<Profile> {
    const data = await this.request<{ data: Profile }>(
      "GET",
      `/v1/profiles/${encodeURIComponent(entityId)}`
    );
    return data.data;
  }

  // ─── Pipeline ─────────────────────────────────────────────────────

  async getPipelineStatus(pipelineId: string): Promise<PipelineStatus> {
    const data = await this.request<{ data: PipelineStatus }>(
      "GET",
      `/v1/pipelines/${encodeURIComponent(pipelineId)}`
    );
    return data.data;
  }

  // ─── Spaces ───────────────────────────────────────────────────────

  async listSpaces(entityId: string): Promise<Space[]> {
    const data = await this.request<{ data: Space[] }>(
      "GET",
      `/v1/spaces?entity_id=${encodeURIComponent(entityId)}`
    );
    return data.data;
  }

  async createSpace(name: string, emoji: string, entityId: string): Promise<Space> {
    const data = await this.request<{ data: Space }>(
      "POST",
      "/v1/spaces",
      { name, emoji, entity_id: entityId }
    );
    return data.data;
  }

  async updateSpace(
    tag: string,
    entityId: string,
    data: { name?: string; emoji?: string }
  ): Promise<Space> {
    const res = await this.request<{ data: Space }>(
      "PATCH",
      `/v1/spaces/${encodeURIComponent(tag)}?entity_id=${encodeURIComponent(entityId)}`,
      data
    );
    return res.data;
  }

  async deleteSpace(tag: string, entityId: string, migrateToDefault = true): Promise<void> {
    await this.request(
      "DELETE",
      `/v1/spaces/${encodeURIComponent(tag)}?entity_id=${encodeURIComponent(entityId)}&migrate_to_default=${migrateToDefault}`
    );
  }

  // ─── Health ───────────────────────────────────────────────────────

  async health(): Promise<{ status: string; version: string; checks?: Record<string, string> }> {
    const data = await this.request<{
      status: string;
      version: string;
      checks?: Record<string, string>;
    }>("GET", "/v1/health");
    return data;
  }
}

// ─── Singleton holder ───────────────────────────────────────────────

let _client: EmeraldClient | null = null;

export function getClient(): EmeraldClient {
  if (!_client) {
    const apiKey =
      typeof window !== "undefined"
        ? localStorage.getItem("emerald_api_key") ?? ""
        : "";
    const baseUrl =
      typeof window !== "undefined"
        ? localStorage.getItem("emerald_base_url") ??
          "http://localhost:8000"
        : "http://localhost:8000";
    const entityId =
      typeof window !== "undefined"
        ? localStorage.getItem("emerald_entity_id") ?? ""
        : "";

    _client = new EmeraldClient({ apiKey, baseUrl, entityId });
  }
  return _client;
}

export function resetClient(): void {
  _client = null;
}
