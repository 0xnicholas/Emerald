/**
 * Emerald SDK — typed data models.
 *
 * Mirrors the Python SDK models 1:1 (AGENTS.md requirement).
 */

/** Returned by client.add() */
export interface AddResult {
  memory_ids: string[];
  pipeline_status: string;
  extracted_count: number;
  pipeline_id?: string;
  conflicts_pending: Record<string, unknown>[];
}

/** A single search hit — either memory or RAG source */
/** One node/edge in a multihop result's provenance path (B4, #33).
 * ``kind`` is "memory", "mention", or a relationship type
 * (UPDATES / EXTENDS / DERIVES_FROM); ``id`` is the node id, or the
 * far-end memory id of an edge step.
 */
export interface SearchPathStep {
  kind: string;
  id: string;
}

export interface SearchResult {
  id: string;
  content: string;
  summary: string;
  score: number;
  source: "memory" | "rag" | string;
  memory_type: string;
  is_latest: boolean;
  container_tag?: string;
  tags?: string[];
  /** Multihop provenance (B4): 0 for seeds, >=1 for graph-reached results. */
  depth: number;
  path: SearchPathStep[];
  document_id?: string;
  document_title?: string;
}

/** Returned by client.search() */
export interface SearchResults {
  results: SearchResult[];
  search_mode: string;
  query_rewritten?: string;
}

/** A single fact in an entity profile */
export interface ProfileFact {
  content: string;
  importance?: number;
  relevance?: number;
  source?: string;
  acquired_at?: string;
}

/** Returned by client.profile() */
export interface Profile {
  entity_id: string;
  static: ProfileFact[];
  dynamic: ProfileFact[];
  memory_count: number;
  computed_at: string;
  version: number;
}

/** Returned by client.health() */
export interface HealthStatus {
  status: string;
  version: string;
  checks: Record<string, string>;
}

/** Returned by client.pipelineStatus() */
export interface PipelineStatus {
  pipeline_id: string;
  status: string;
  stage: string;
  document_id?: string;
  content_type: string;
  error_message?: string;
  fact_extraction_status?: "success" | "failed" | "skipped" | null;
  memory_count: number;
}

/** Options for client.add() */
export interface AddOptions {
  content_type?: string;
  title?: string;
  metadata?: Record<string, unknown>;
  require_confirmation_for_high_impact?: boolean;
  memory_type?: "fact" | "preference" | "episodic";
  confidence?: number;
  valid_until?: Date;
}

/** Options for client.search() */
export interface SearchOptions {
  search_mode?: "hybrid" | "memory" | "rag";
  top_k?: number;
  rerank?: boolean;
  rewrite_query?: boolean;
  filters?: Record<string, unknown>;
  /** Space filter (ADR-0002): restrict results to this container_tag; omit = full pool. */
  container_tag?: string;
  min_confidence?: number;
  dynamic_truncation?: boolean;
  /** Entity-centric retrieval (B4): mention canonical form or id. */
  about?: string;
  /** Graph traversal hops over shared-subject mention bridges (B4, 0-4). */
  depth?: number;
}

/** Options for client.upload() */
export interface UploadOptions {
  content_type?: string;
  title?: string;
}
