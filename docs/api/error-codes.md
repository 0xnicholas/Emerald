# Emerald Error Code Reference

All Emerald API errors return a standardized JSON body with a machine-readable
`error_code` field. Use this reference to handle errors programmatically.

## Response Format

```json
{
  "error_code": "MEMORY_NOT_FOUND",
  "message": "The requested memory does not exist or has been deleted",
  "details": [],
  "request_id": "a1b2c3d4"
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `error_code` | string | Machine-readable error identifier (e.g. `MEMORY_NOT_FOUND`) |
| `message` | string | Human-readable description |
| `details` | array | Additional context, typically validation errors with `field`/`message` |
| `request_id` | string | Request ID for correlating with server logs |

## Error Codes

### Auth (401/403)

| Code | HTTP | Description |
|---|---|---|
| `AUTH_INVALID_KEY` | 401 | API key is missing, invalid, or expired |
| `AUTH_INSUFFICIENT_PERMISSIONS` | 403 | API key lacks required permissions |
| `ENTITY_UNAUTHORIZED` | 403 | API key is not authorized for the requested entity |

### Validation (422)

| Code | HTTP | Description |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body or parameters failed validation |
| `INVALID_CONTENT_TYPE` | 422 | The provided content type is not supported |
| `CONTENT_TOO_LARGE` | 422 | Uploaded content exceeds the size limit |
| `INVALID_PAGINATION_TOKEN` | 422 | The provided page_token is invalid or expired |

### Not Found (404)

| Code | HTTP | Description |
|---|---|---|
| `MEMORY_NOT_FOUND` | 404 | Memory does not exist or has been deleted |
| `PROFILE_NOT_FOUND` | 404 | Profile does not exist |
| `PIPELINE_NOT_FOUND` | 404 | Pipeline job does not exist |
| `SESSION_NOT_FOUND` | 404 | Session does not exist or has expired |
| `ROUTE_NOT_FOUND` | 404 | API route does not exist |
| `FILE_NOT_FOUND` | 404 | File was not found in storage |

### Conflict (409)

| Code | HTTP | Description |
|---|---|---|
| `MEMORY_ALREADY_EXISTS` | 409 | A memory with the same `idempotency_key` already exists |
| `DUPLICATE_RESOURCE` | 409 | A resource with the same identifier already exists |

### Rate Limit (429)

| Code | HTTP | Description |
|---|---|---|
| `RATE_LIMITED` | 429 | Too many requests. See `Retry-After` header. |

### Server Errors (500/502/503)

| Code | HTTP | Description |
|---|---|---|
| `INTERNAL_ERROR` | 500 | Unexpected internal error |
| `PIPELINE_FAILED` | 500 | A pipeline stage failed |
| `EXTRACTION_FAILED` | 500 | Content extraction failed |
| `EMBEDDING_FAILED` | 500 | Embedding generation failed |
| `CONNECTOR_AUTH_FAILED` | 502 | OAuth authentication with external provider failed |
| `SERVICE_UNAVAILABLE` | 503 | A dependent service is temporarily unavailable |

### Connector (400/502)

| Code | HTTP | Description |
|---|---|---|
| `CONNECTOR_NOT_SUPPORTED` | 400 | The requested connector provider is not supported |
| `CONNECTOR_WEBHOOK_INVALID` | 400 | Received invalid webhook payload |
| `CONNECTOR_AUTH_FAILED` | 502 | OAuth authentication failed |

## SDK Usage

### Python

```python
from emerald.sdk import EmeraldClient
from emerald.sdk.exceptions import EmeraldNotFoundError, EmeraldAuthError

client = EmeraldClient()

try:
    memory = await client.get_memory("mem_123")
except EmeraldNotFoundError as e:
    print(f"Not found: {e.error_code} — {e}")
except EmeraldAuthError as e:
    print(f"Auth error: {e.error_code}")
```

All SDK exceptions expose `.error_code` for programmatic handling.

## Pagination

Cursor-based pagination uses `page_token` parameters and returns `pagination` metadata:

```json
{
  "data": { "items": [...] },
  "pagination": {
    "next_page_token": "eyJjIjogImFiYzEyMyIs...",
    "has_more": true
  }
}
```

Pass `next_page_token` as `page_token` in the next request to fetch the next page.
