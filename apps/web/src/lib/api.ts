import type {
  AddMemoryResult,
  EmeraldConfig,
  Memory,
  PipelineStatus,
  Profile,
  SearchMemory,
  Space,
} from "./types";

export interface UploadResult {
  document_id: string;
  pipeline_id: string;
  pipeline_status: string;
  file_size_bytes: number;
  content_type: string;
  title: string;
}

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
    // FormData（文件上传）：不设 Content-Type，由浏览器携带 multipart boundary
    const isForm = body instanceof FormData;
    const headers: Record<string, string> = isForm
      ? { Authorization: `Bearer ${this.config.apiKey}` }
      : this.headers;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let res: Response;
    try {
      res = await fetch(url, {
        method,
        headers,
        body: body ? (isForm ? (body as FormData) : JSON.stringify(body)) : undefined,
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
      containerTag?: string;
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
        container_tag: opts?.containerTag,
      }
    );
    return data.data;
  }

  async upload(
    file: File,
    entityId: string,
    opts?: { contentType?: string; title?: string }
  ): Promise<UploadResult> {
    const form = new FormData();
    form.append("file", file);
    form.append("entity_id", entityId);
    if (opts?.contentType) form.append("content_type", opts.contentType);
    if (opts?.title) form.append("title", opts.title);
    const data = await this.request<{ data: UploadResult }>("POST", "/v1/upload", form);
    return data.data;
  }

  async updateMemory(
    id: string,
    data: { content?: string; summary?: string; memory_type?: string; confidence?: number; tags?: string[] }
  ): Promise<void> {
    await this.request("PATCH", `/v1/memories/${encodeURIComponent(id)}`, data);
  }

  async updateMemoryTags(id: string, tags: string[]): Promise<void> {
    await this.request("PATCH", `/v1/memories/${encodeURIComponent(id)}`, { tags });
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

  // ─── Graph ────────────────────────────────────────────────────────

  async getGraph(entityId: string, limit = 150): Promise<{ nodes: { id: string; label: string; type: string; confidence: number }[]; edges: { source: string; target: string; type: string; aspect?: string }[] }> {
    const data = await this.request<{ data: { nodes: any[]; edges: any[] } }>(
      "GET",
      `/v1/memories/graph?entity_id=${encodeURIComponent(entityId)}&limit=${limit}`
    );
    return data.data;
  }

  // ─── URL Extract ─────────────────────────────────────────────────

  async extractUrl(url: string): Promise<{ url: string; title: string; description: string; favicon: string; image: string; site_name: string }> {
    const data = await this.request<{ data: { url: string; title: string; description: string; favicon: string; image: string; site_name: string } }>(
      "POST",
      "/v1/extract-url",
      { url }
    );
    return data.data;
  }

  // ─── Sources (ADR-0004 connection hub bindings) ─────────────────

  async listSources(entityId: string): Promise<{
    id: string;
    provider: string;
    hub_account_id: string;
    sync_status: string;
    last_synced_at: string | null;
    error_message: string | null;
  }[]> {
    const data = await this.request<{
      data: {
        id: string;
        provider: string;
        hub_account_id: string;
        sync_status: string;
        last_synced_at: string | null;
        error_message: string | null;
      }[];
    }>("GET", `/v1/sources?entity_id=${encodeURIComponent(entityId)}`);
    return data.data;
  }

  async connectSource(entityId: string, provider: string): Promise<{ auth_link_url: string; session_id: string; provider: string }> {
    const data = await this.request<{ data: { auth_link_url: string; session_id: string; provider: string } }>(
      "POST",
      "/v1/sources/connect",
      { entity_id: entityId, provider }
    );
    return data.data;
  }

  async refreshSources(entityId: string): Promise<{ accounts: number; bindings: string[] }> {
    const data = await this.request<{ data: { accounts: number; bindings: string[] } }>(
      "POST",
      `/v1/sources/refresh?entity_id=${encodeURIComponent(entityId)}`
    );
    return data.data;
  }

  async deleteSource(bindingId: string, entityId: string): Promise<void> {
    await this.request(
      "DELETE",
      `/v1/sources/${encodeURIComponent(bindingId)}?entity_id=${encodeURIComponent(entityId)}`
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
        ? localStorage.getItem("emerald_base_url") ?? ""
        : "";  // H1 同源默认：空 = 相对路径，经 nginx :80 代理
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
