# Emerald TypeScript SDK

TypeScript/JavaScript client for [Emerald](https://github.com/emerald-ai/emerald) — AI Agent memory and context infrastructure.

## Installation

```bash
npm install @emerald/sdk
```

## Quick Start

```ts
import { EmeraldClient } from "@emerald/sdk";

const client = new EmeraldClient({ apiKey: "em_your_api_key" });

// Add a memory
const result = await client.add("User prefers TypeScript", "user_123");
console.log(result.memory_ids); // ["mem_abc123"]

// Search memories
const searchResults = await client.search("TypeScript", "user_123");
console.log(searchResults.results[0].content);

// Get user profile
const profile = await client.profile("user_123");
console.log(profile.static); // long-term facts
console.log(profile.dynamic); // recent episodic facts

// Upload a file
const uploadResult = await client.upload(file, "user_123");
console.log(uploadResult.pipeline_id); // track async processing
```

## API

### `new EmeraldClient(config)`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `apiKey` | `string` | `process.env.EMERALD_API_KEY` | Emerald API key (prefix `em_`) |
| `baseUrl` | `string` | `http://localhost:8000` | API base URL |
| `apiVersion` | `"v1" \| "v2"` | `"v1"` | API version |
| `timeout` | `number` | `30000` | Request timeout in ms |

### Core Methods

All four required by AGENTS.md:

```ts
client.add(content: string, entityId: string, opts?: AddOptions): Promise<AddResult>
client.search(q: string, entityId: string, opts?: SearchOptions): Promise<SearchResults>
client.profile(entityId: string): Promise<Profile>
client.upload(file: File | { name, data }, entityId: string, opts?: UploadOptions): Promise<AddResult>
```

#### `SearchOptions`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `search_mode` | `"hybrid" \| "memory" \| "rag"` | `"hybrid"` | `hybrid` returns memories + RAG documents in one call |
| `top_k` | `number` | `30` | Max results (1–100) |
| `rerank` | `boolean` | `false` | Enable cross-encoder re-ranking |
| `rewrite_query` | `boolean` | `false` | Enable LLM query expansion |
| `filters` | `object` | — | Metadata filters, MongoDB-style operators: `$and`, `$or`, `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte` |
| `min_confidence` | `number` | — | Minimum memory confidence (0–1) |
| `dynamic_truncation` | `boolean` | `true` | Cut off results at score cliffs |
| `about` | `string` | — | Entity-centric retrieval: a mention canonical form or mention id; returns the entity's latest memories mentioning it across surface forms (skips RAG/fast-lane) |
| `depth` | `number` | `0` | Graph traversal hops (0–4) over shared-subject mention bridges + relationship chains (`UPDATES` / `EXTENDS` / `DERIVES_FROM`) |

#### `AddOptions`

| Field | Type | Description |
|-------|------|-------------|
| `content_type` | `string` | `text` (default), `conversation`, `url`, `code`, `markdown` |
| `title` | `string` | Optional title |
| `metadata` | `object` | Custom key-value metadata |
| `memory_type` | `"fact" \| "preference" \| "episodic"` | Override the LLM-extracted type |
| `confidence` | `number` | Override the LLM confidence score (0–1); skips re-scoring |
| `valid_until` | `Date` | Expiry timestamp; the memory is marked non-latest after this point |
| `require_confirmation_for_high_impact` | `boolean` | Flag high-impact contradictions for confirmation instead of auto-resolving |

#### `UploadOptions`

| Field | Type | Description |
|-------|------|-------------|
| `content_type` | `string` | MIME type hint (auto-detected if omitted) |
| `title` | `string` | File title (also used as filename in Node.js) |

#### Multi-hop retrieval example

```ts
// All latest memories about Google, plus 2-hop graph expansion
const results = await client.search("Google", "user_123", {
  search_mode: "memory",
  about: "Google", // entity-centric: mention canonical form or id
  depth: 2,        // up to 4 hops over mention bridges + relationship chains
});
for (const r of results.results) {
  if (r.depth > 0) {
    // provenance path: seed → mention/relationship steps → this result
    console.log(r.depth, r.path.map((s) => `${s.kind}:${s.id.slice(0, 8)}`).join(" → "));
  }
}
```

### Utility Methods

```ts
client.health(): Promise<HealthStatus>
client.pipelineStatus(pipelineId: string): Promise<PipelineStatus>
client.getMemory(memoryId: string): Promise<Record<string, unknown>>
```

## Error Handling

All errors extend `EmeraldError`. Catch the base class or specific subclasses:

```ts
import { EmeraldClient, EmeraldNotFoundError, EmeraldRateLimitError } from "@emerald/sdk";

const client = new EmeraldClient();

try {
  await client.getMemory("mem_123");
} catch (e) {
  if (e instanceof EmeraldNotFoundError) {
    console.log("Memory not found");
  } else if (e instanceof EmeraldRateLimitError) {
    console.log(`Retry after ${e.retryAfter} seconds`);
  }
}
```

### Exception Hierarchy

| Exception | HTTP | Description |
|-----------|------|-------------|
| `EmeraldAuthError` | 401/403 | Invalid or unauthorized API key |
| `EmeraldNotFoundError` | 404 | Resource not found |
| `EmeraldValidationError` | 422 | Validation failure (`.fieldErrors`) |
| `EmeraldRateLimitError` | 429 | Rate limited (`.retryAfter`) |
| `EmeraldServerError` | 5xx | Server error |
| `EmeraldNetworkError` | — | Connection/DNS failure |

## See also

- [SDK guide (Python ↔ TypeScript)](../../docs/api/sdk-guide.md) — Python-side docs and the method mapping table
- [REST API guide](../../docs/api/rest-guide.md) — full REST surface, including the REST-only admin extension endpoints (keys, sessions, conflicts, spaces) not exposed by any SDK (AGENTS.md principle 7)
- [Quickstart](../../docs/quickstart.md)

## Development

```bash
npm install
npm test        # Run tests with vitest
npm run build   # Compile TypeScript
```

## License

MIT
