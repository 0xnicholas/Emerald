// ─── Emerald API Types ──────────────────────────────────────────────

export interface Memory {
  id: string;
  content: string;
  summary: string;
  memory_type: "fact" | "preference" | "episodic";
  is_latest: boolean;
  confidence: number;
  valid_from?: string;
  valid_until?: string;
  entity_id: string;
  validation_count: number;
  created_at?: string;
  updated_at?: string;
  // Search result extras
  score?: number;
  source?: "memory" | "rag";
  document_id?: string;
  document_title?: string;
}

export interface SearchMemory {
  id: string;
  content: string;
  summary: string;
  score: number;
  source: string;
  memory_type: string;
  container_tag?: string;
  is_latest: boolean;
  document_id?: string;
  document_title?: string;
}

export interface Profile {
  entity_id: string;
  static: ProfileFact[];
  dynamic: DynamicFact[];
  memory_count: number;
  computed_at: string;
  version: number;
}

export interface ProfileFact {
  content: string;
  importance: number;
}

export interface DynamicFact {
  content: string;
  relevance: number;
  source: string;
  acquired_at?: string;
}

export interface SearchResults {
  results: SearchMemory[];
  search_mode: string;
  query_rewritten?: string;
}

export interface PaginationMeta {
  next_token?: string;
  has_more: boolean;
  limit: number;
}

export interface AddMemoryResult {
  memory_ids: string[];
  pipeline_status: string;
  extracted_count: number;
  conflicts_pending: string[];
}

export interface PipelineStatus {
  pipeline_id: string;
  status: string;
  stage: string;
  document_id?: string;
  content_type: string;
  error_message?: string;
  fact_extraction_status?: string;
  memory_count: number;
}

// ─── Space ──────────────────────────────────────────────────────────

export interface Space {
  containerTag: string;
  name: string;
  emoji: string;
  entityId: string;
  memoryCount: number;
  createdAt: string;
  updatedAt: string;
}

// ─── App Config ─────────────────────────────────────────────────────

export interface EmeraldConfig {
  apiKey: string;
  baseUrl: string;
  entityId: string;
}
