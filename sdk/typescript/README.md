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

## Development

```bash
npm install
npm test        # Run tests with vitest
npm run build   # Compile TypeScript
```

## License

MIT
