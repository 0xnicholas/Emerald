/**
 * Emerald TypeScript SDK client.
 *
 * Four core methods (AGENTS.md):
 * - add(content, entityId)       → POST /v1/memories
 * - search(q, entityId)          → POST /v1/search
 * - profile(entityId)            → GET /v1/profiles/{id}
 * - upload(file, entityId)       → POST /v1/upload
 *
 * Usage:
 *   const client = new EmeraldClient({ apiKey: "em_xxx" });
 *   const result = await client.add("user likes TypeScript", "user_123");
 *   const profile = await client.profile("user_123");
 *
 * Errors are surfaced as typed exceptions — see exceptions.ts.
 *
 * Requires Node.js >= 18.0.0 (uses fetch, AbortSignal.timeout).
 */

import { SDK_VERSION } from "./version.js";
import {
  EmeraldNetworkError,
  EmeraldServerError,
  raiseForStatus,
} from "./exceptions.js";
import type {
  AddOptions,
  AddResult,
  HealthStatus,
  PipelineStatus,
  Profile,
  SearchOptions,
  SearchResults,
  UploadOptions,
} from "./models.js";

export type { AddOptions, AddResult, HealthStatus, PipelineStatus, Profile, ProfileFact, SearchOptions, SearchResult, SearchResults, UploadOptions } from "./models.js";
export { EmeraldAuthError, EmeraldError, EmeraldNetworkError, EmeraldNotFoundError, EmeraldRateLimitError, EmeraldServerError, EmeraldValidationError } from "./exceptions.js";

export interface EmeraldClientConfig {
  apiKey?: string;
  baseUrl?: string;
  apiVersion?: "v1" | "v2";
  /** Request timeout in ms (default: 30000) */
  timeout?: number;
  /** Maximum retries for 5xx errors (default: 3, matches Python SDK) */
  maxRetries?: number;
  /** Custom fetch implementation (for testing or Node.js < 18) */
  fetch?: typeof globalThis.fetch;
}

const DEFAULT_BASE_URL = "http://localhost:8000";
const DEFAULT_MAX_RETRIES = 3;

// ── AbortSignal.timeout polyfill (for older runtimes) ──────────────

function createAbortSignal(timeoutMs: number): AbortSignal {
  if (typeof AbortSignal.timeout === "function") {
    return AbortSignal.timeout(timeoutMs);
  }
  // Fallback for runtimes without AbortSignal.timeout static method
  const controller = new AbortController();
  setTimeout(() => controller.abort(new DOMException("Timeout", "TimeoutError")), timeoutMs);
  return controller.signal;
}

export class EmeraldClient {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly apiVersion: string;
  readonly timeout: number;
  readonly maxRetries: number;
  private readonly _fetch: typeof globalThis.fetch;

  constructor(config: EmeraldClientConfig = {}) {
    this.apiKey = config.apiKey ?? process.env.EMERALD_API_KEY ?? "";
    this.baseUrl = (config.baseUrl ?? process.env.EMERALD_BASE_URL ?? DEFAULT_BASE_URL).replace(/\/$/, "");
    this.apiVersion = config.apiVersion ?? "v1";
    this.timeout = config.timeout ?? 30_000;
    this.maxRetries = config.maxRetries ?? DEFAULT_MAX_RETRIES;
    this._fetch = config.fetch ?? globalThis.fetch.bind(globalThis);
  }

  // ── Private request plumbing ──────────────────────────────────────

  private async _request(
    method: string,
    path: string,
    opts: {
      body?: unknown;
      headers?: Record<string, string>;
      timeout?: number;
      rawBody?: BodyInit;
    } = {},
  ): Promise<unknown> {
    const url = `${this.baseUrl}${path}`;
    const requestTimeout = opts.timeout ?? this.timeout;

    let lastError: Error | undefined;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      const headers: Record<string, string> = {
        Authorization: `Bearer ${this.apiKey}`,
        "User-Agent": `emerald-sdk-ts/${SDK_VERSION}`,
        ...opts.headers,
      };

      const init: RequestInit = {
        method,
        headers,
        signal: createAbortSignal(requestTimeout),
      };

      if (opts.rawBody) {
        // For multipart uploads — let the browser set Content-Type with boundary
        delete headers["Content-Type"];
        init.body = opts.rawBody;
      } else if (opts.body !== undefined) {
        headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(opts.body);
      }

      let response: Response;
      try {
        response = await this._fetch(url, init);
      } catch (err) {
        lastError = new EmeraldNetworkError(
          `Network error contacting Emerald API: ${err instanceof Error ? err.message : String(err)}`,
        );
        // Don't retry network errors on uploads (large payloads)
        if (opts.rawBody) throw lastError;
        if (attempt < this.maxRetries) {
          await this._backoff(attempt);
          continue;
        }
        throw lastError;
      }

      // Retry on 5xx (transient server errors)
      if (response.status >= 500 && response.status < 600 && attempt < this.maxRetries) {
        // Don't retry non-idempotent POST with raw body
        if (method === "POST" && opts.rawBody) {
          let body: unknown;
          try { body = await response.json(); } catch { body = null; }
          raiseForStatus(response, body);
        }
        await this._backoff(attempt);
        continue;
      }

      let body: unknown;
      try {
        body = await response.json();
      } catch {
        body = null;
      }

      if (!response.ok) {
        raiseForStatus(response, body);
      }

      return body;
    }

    // Should not reach here, but TypeScript needs it
    throw lastError ?? new EmeraldServerError("Request failed after all retries");
  }

  /** Exponential backoff: 1s, 2s, 4s, ... */
  private async _backoff(attempt: number): Promise<void> {
    const delay = Math.min(1000 * Math.pow(2, attempt), 10_000);
    await new Promise((resolve) => setTimeout(resolve, delay));
  }

  // ── Core methods ──────────────────────────────────────────────────

  /**
   * Add content to the memory graph.
   *
   * @param content - Text content to ingest.
   * @param entityId - Entity (user, project, org) this content belongs to.
   * @param opts - Optional overrides (content_type, memory_type, confidence, etc.)
   */
  async add(
    content: string,
    entityId: string,
    opts: AddOptions = {},
  ): Promise<AddResult> {
    const body: Record<string, unknown> = {
      content,
      entity_id: entityId,
      content_type: opts.content_type ?? "text",
      require_confirmation_for_high_impact: opts.require_confirmation_for_high_impact ?? false,
    };
    if (opts.title) body.title = opts.title;
    if (opts.metadata) body.metadata = opts.metadata;
    if (opts.memory_type !== undefined) body.memory_type = opts.memory_type;
    if (opts.confidence !== undefined) body.confidence = opts.confidence;
    if (opts.valid_until) body.valid_until = opts.valid_until.toISOString();

    const resp = (await this._request("POST", `/${this.apiVersion}/memories`, { body })) as {
      data: Record<string, unknown>;
    };
    const d = resp.data;
    return {
      memory_ids: (d.memory_ids as string[]) ?? [],
      pipeline_status: (d.pipeline_status as string) ?? "done",
      extracted_count: (d.extracted_count as number) ?? 0,
      pipeline_id: d.pipeline_id as string | undefined,
      conflicts_pending: (d.conflicts_pending as Record<string, unknown>[]) ?? [],
    };
  }

  /**
   * Hybrid search across memory (graph) and RAG (vector).
   *
   * @param q - Search query.
   * @param entityId - Entity scope.
   * @param opts - Search options (mode, top_k, rerank, filters, etc.)
   */
  async search(
    q: string,
    entityId: string,
    opts: SearchOptions = {},
  ): Promise<SearchResults> {
    const body: Record<string, unknown> = {
      q,
      entity_id: entityId,
      search_mode: opts.search_mode ?? "hybrid",
      top_k: opts.top_k ?? 30,
      rerank: opts.rerank ?? false,
      rewrite_query: opts.rewrite_query ?? false,
      dynamic_truncation: opts.dynamic_truncation ?? true,
    };
    if (opts.filters) body.filters = opts.filters;
    if (opts.min_confidence !== undefined) body.min_confidence = opts.min_confidence;

    const resp = (await this._request("POST", `/${this.apiVersion}/search`, { body })) as {
      data: Record<string, unknown>;
    };
    const d = resp.data;
    const results = (d.results as Record<string, unknown>[]) ?? [];
    return {
      results: results.map((r) => ({
        id: (r.id as string) ?? "",
        content: (r.content as string) ?? "",
        summary: (r.summary as string) ?? "",
        score: (r.score as number) ?? 0,
        source: (r.source as string) ?? "memory",
        memory_type: (r.memory_type as string) ?? "",
        is_latest: (r.is_latest as boolean) ?? true,
        document_id: r.document_id as string | undefined,
        document_title: r.document_title as string | undefined,
      })),
      search_mode: (d.search_mode as string) ?? "hybrid",
      query_rewritten: d.query_rewritten as string | undefined,
    };
  }

  /**
   * Get entity profile (static + dynamic facts).
   *
   * @param entityId - The entity to profile.
   */
  async profile(entityId: string): Promise<Profile> {
    const resp = (await this._request("GET", `/${this.apiVersion}/profiles/${entityId}`)) as {
      data: Record<string, unknown>;
    };
    const d = resp.data;
    return {
      entity_id: (d.entity_id as string) ?? entityId,
      static: ((d.static as Record<string, unknown>[]) ?? []).map((f) => ({
        content: (f.content as string) ?? "",
        importance: (f.importance as number) ?? 1,
      })),
      dynamic: ((d.dynamic as Record<string, unknown>[]) ?? []).map((f) => ({
        content: (f.content as string) ?? "",
        relevance: (f.relevance as number) ?? 1,
        source: (f.source as string) ?? "",
        acquired_at: (f.acquired_at as string) ?? "",
      })),
      memory_count: (d.memory_count as number) ?? 0,
      computed_at: (d.computed_at as string) ?? "",
      version: (d.version as number) ?? 1,
    };
  }

  /**
   * Upload a file for async processing (max 50MB).
   *
   * @param file - File object (browser) or { name, data: Buffer | Blob } (Node).
   * @param entityId - Entity this file belongs to.
   * @param opts - Optional content_type and title.
   */
  async upload(
    file: File | { name: string; data: Blob | Uint8Array },
    entityId: string,
    opts: UploadOptions = {},
  ): Promise<AddResult> {
    const formData = new FormData();
    if (file instanceof File) {
      formData.append("file", file, file.name);
    } else {
      const blob = file.data instanceof Blob
        ? file.data
        : new Blob([file.data as BlobPart], { type: opts.content_type ?? "application/octet-stream" });
      formData.append("file", blob, file.name);
    }
    formData.append("entity_id", entityId);
    if (opts.title) formData.append("title", opts.title);

    const resp = (await this._request("POST", `/${this.apiVersion}/upload`, {
      rawBody: formData,
      timeout: 120_000, // 2 min for large files
    })) as {
      data: Record<string, unknown>;
    };
    const d = resp.data;
    return {
      memory_ids: [],
      pipeline_status: (d.pipeline_status as string) ?? "queued",
      pipeline_id: d.pipeline_id as string | undefined,
      extracted_count: 0,
      conflicts_pending: [],
    };
  }

  // ── Utility methods ───────────────────────────────────────────────

  /** Check API health. */
  async health(): Promise<HealthStatus> {
    const resp = (await this._request("GET", `/${this.apiVersion}/health`)) as Record<string, unknown>;
    return {
      status: (resp.status as string) ?? "unknown",
      version: (resp.version as string) ?? "",
      checks: (resp.checks as Record<string, string>) ?? {},
    };
  }

  /** Check async pipeline processing status. */
  async pipelineStatus(pipelineId: string): Promise<PipelineStatus> {
    const resp = (await this._request("GET", `/${this.apiVersion}/pipelines/${pipelineId}`)) as {
      data: Record<string, unknown>;
    };
    const d = resp.data;
    return {
      pipeline_id: (d.pipeline_id as string) ?? pipelineId,
      status: (d.status as string) ?? "unknown",
      stage: (d.stage as string) ?? "",
      document_id: d.document_id as string | undefined,
      content_type: (d.content_type as string) ?? "",
      error_message: d.error_message as string | undefined,
      fact_extraction_status: d.fact_extraction_status as "success" | "failed" | "skipped" | null | undefined,
      memory_count: (d.memory_count as number) ?? 0,
    };
  }

  /** Get a single memory by ID. */
  async getMemory(memoryId: string): Promise<Record<string, unknown>> {
    const resp = (await this._request("GET", `/${this.apiVersion}/memories/${memoryId}`)) as {
      data: Record<string, unknown>;
    };
    return resp.data;
  }
}
