/**
 * Emerald SDK — typed exception hierarchy.
 *
 * Mirrors the Python SDK exceptions 1:1.
 * All exceptions extend EmeraldError so callers can catch broadly.
 *
 * | HTTP | Exception                  | Scenario                                 |
 * |------|----------------------------|------------------------------------------|
 * | 401  | EmeraldAuthError           | API key invalid or expired               |
 * | 404  | EmeraldNotFoundError       | Memory / profile / pipeline not found    |
 * | 422  | EmeraldValidationError     | Request body validation failure          |
 * | 429  | EmeraldRateLimitError      | Rate limit (carries retryAfter)           |
 * | 5xx  | EmeraldServerError         | Server-side error                        |
 * | net  | EmeraldNetworkError        | Connection timeout, DNS failure          |
 */

export class EmeraldError extends Error {
  /** Machine-readable error code from the server (v2 format). */
  errorCode?: string;

  constructor(message: string, errorCode?: string) {
    super(message);
    this.name = "EmeraldError";
    this.errorCode = errorCode;
  }
}

export class EmeraldAuthError extends EmeraldError {
  constructor(message: string, errorCode?: string) {
    super(message, errorCode);
    this.name = "EmeraldAuthError";
  }
}

export class EmeraldNotFoundError extends EmeraldError {
  constructor(message: string, errorCode?: string) {
    super(message, errorCode);
    this.name = "EmeraldNotFoundError";
  }
}

export class EmeraldValidationError extends EmeraldError {
  /** Field-level errors: { fieldName: errorMessage } */
  fieldErrors: Record<string, string>;

  constructor(
    message: string,
    fieldErrors?: Record<string, string>,
    errorCode?: string,
  ) {
    super(message, errorCode);
    this.name = "EmeraldValidationError";
    this.fieldErrors = fieldErrors ?? {};
  }
}

export class EmeraldRateLimitError extends EmeraldError {
  /** Seconds until the rate limit resets. */
  retryAfter?: number;

  constructor(message: string, retryAfter?: number, errorCode?: string) {
    super(message, errorCode);
    this.name = "EmeraldRateLimitError";
    this.retryAfter = retryAfter;
  }
}

export class EmeraldServerError extends EmeraldError {
  constructor(message: string, errorCode?: string) {
    super(message, errorCode);
    this.name = "EmeraldServerError";
  }
}

export class EmeraldNetworkError extends EmeraldError {
  constructor(message: string) {
    super(message);
    this.name = "EmeraldNetworkError";
  }
}

// ── Internal helpers ─────────────────────────────────────────────────

/** Map HTTP status → exception constructor. */
const STATUS_MAP: Record<number, new (message: string, errorCode?: string) => EmeraldError> = {
  401: EmeraldAuthError,
  403: EmeraldAuthError,
  404: EmeraldNotFoundError,
  422: EmeraldValidationError as unknown as new (message: string, errorCode?: string) => EmeraldError,
  429: EmeraldRateLimitError as unknown as new (message: string, errorCode?: string) => EmeraldError,
};

function extractErrorMessage(body: unknown, statusText: string): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    // v2 format: {"error_code": "...", "message": "..."}
    if (typeof b.message === "string") return b.message;
    // v1 format: {"error": {"code": "...", "message": "..."}}
    const err = b.error;
    if (err && typeof err === "object") {
      const e = err as Record<string, unknown>;
      if (typeof e.message === "string") return e.message;
    }
  }
  return statusText;
}

function extractErrorCode(body: unknown): string | undefined {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.error_code === "string") return b.error_code;
  }
  return undefined;
}

function extractRetryAfter(response: Response): number | undefined {
  const raw = response.headers.get("Retry-After");
  if (raw) {
    const n = parseInt(raw, 10);
    if (!isNaN(n)) return n;
  }
  return undefined;
}

function extractFieldErrors(body: unknown): Record<string, string> | undefined {
  if (!body || typeof body !== "object") return undefined;
  const b = body as Record<string, unknown>;

  // v2 format: {"details": [{"field": "...", "message": "..."}, ...]}
  const details = b.details;
  if (Array.isArray(details)) {
    const result: Record<string, string> = {};
    for (const d of details) {
      if (d && typeof d === "object") {
        const item = d as Record<string, unknown>;
        if (typeof item.field === "string" && typeof item.message === "string") {
          result[item.field] = item.message;
        }
      }
    }
    if (Object.keys(result).length > 0) return result;
  }

  return undefined;
}

/**
 * Raise a typed SDK exception from a non-2xx response.
 * Callers should catch EmeraldError or specific subclasses.
 */
export function raiseForStatus(response: Response, body: unknown): never {
  const status = response.status;
  const msg = extractErrorMessage(body, response.statusText);
  const errorCode = extractErrorCode(body);

  let Exc: new (message: string, errorCode?: string) => EmeraldError;
  if (status >= 500) {
    Exc = EmeraldServerError;
  } else {
    Exc = STATUS_MAP[status] ?? EmeraldError;
  }

  // Special-cased subclasses with extra fields (detect by status code,
  // since STATUS_MAP uses type casts for the generic signature).
  if (status === 429) {
    const retryAfter = extractRetryAfter(response);
    throw new EmeraldRateLimitError(msg, retryAfter, errorCode);
  }
  if (status === 422) {
    const fieldErrors = extractFieldErrors(body);
    throw new EmeraldValidationError(msg, fieldErrors, errorCode);
  }
  throw new Exc(msg, errorCode);
}
