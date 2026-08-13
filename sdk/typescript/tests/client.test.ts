/**
 * Emerald TypeScript SDK — unit tests.
 *
 * Tests run against a mock fetch to avoid needing a live Emerald instance.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { EmeraldClient } from "../src/client.js";
import {
  EmeraldAuthError,
  EmeraldNotFoundError,
  EmeraldRateLimitError,
  EmeraldValidationError,
  EmeraldServerError,
  EmeraldNetworkError,
  EmeraldError,
} from "../src/exceptions.js";

function mockResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: new Headers(headers),
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

function createClient(responses: Response[]) {
  let i = 0;
  const mockFetch = vi.fn(() => Promise.resolve(responses[i++]));
  return new EmeraldClient({ apiKey: "em_test", baseUrl: "http://test", fetch: mockFetch as unknown as typeof fetch });
}

describe("EmeraldClient", () => {
  it("should construct with defaults", () => {
    const client = new EmeraldClient();
    expect(client.apiVersion).toBe("v1");
  });

  it("should use v2 when configured", () => {
    const client = new EmeraldClient({ apiVersion: "v2" });
    expect(client.apiVersion).toBe("v2");
  });
});

describe("add()", () => {
  it("should return AddResult on success", async () => {
    const client = createClient([
      mockResponse({ data: { memory_ids: ["mem_1", "mem_2"], pipeline_status: "done", extracted_count: 2 } }),
    ]);
    const result = await client.add("hello", "user_1");
    expect(result.memory_ids).toEqual(["mem_1", "mem_2"]);
    expect(result.pipeline_status).toBe("done");
    expect(result.extracted_count).toBe(2);
  });

  it("should pass memory_type override", async () => {
    const mockFetch = vi.fn(() =>
      Promise.resolve(mockResponse({ data: { memory_ids: ["mem_1"], pipeline_status: "done", extracted_count: 1 } })),
    );
    const client = new EmeraldClient({ apiKey: "em_test", baseUrl: "http://test", fetch: mockFetch as unknown as typeof fetch });
    await client.add("hello", "user_1", { memory_type: "preference", confidence: 0.9 });
    const call = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(call[1].body as string);
    expect(body.memory_type).toBe("preference");
    expect(body.confidence).toBe(0.9);
  });
});

describe("search()", () => {
  it("should return search results", async () => {
    const client = createClient([
      mockResponse({
        data: {
          results: [{ id: "mem_1", content: "test", score: 0.95, source: "memory", memory_type: "fact", is_latest: true }],
          search_mode: "memory",
        },
      }),
    ]);
    const results = await client.search("test", "user_1");
    expect(results.results).toHaveLength(1);
    expect(results.results[0].id).toBe("mem_1");
  });

  it("should forward the about option (B4 entity-centric retrieval)", async () => {
    const mockFetch = vi.fn(() =>
      Promise.resolve(
        mockResponse({
          data: {
            results: [{ id: "mem_1", content: "在 Google 工作", score: 0.8, source: "memory", memory_type: "fact", is_latest: true }],
            search_mode: "memory",
          },
        }),
      ),
    );
    const client = new EmeraldClient({ apiKey: "em_test", baseUrl: "http://test", fetch: mockFetch as unknown as typeof fetch });
    await client.search("", "user_1", { about: "Google" });
    const call = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(call[1].body as string);
    expect(body.about).toBe("Google");
  });
});

describe("profile()", () => {
  it("should return profile", async () => {
    const client = createClient([
      mockResponse({
        data: {
          entity_id: "user_1",
          static: [{ content: "likes TS", importance: 0.9 }],
          dynamic: [{ content: "working on Emerald", relevance: 0.8 }],
          memory_count: 42,
          computed_at: "2026-07-03T00:00:00Z",
          version: 1,
        },
      }),
    ]);
    const profile = await client.profile("user_1");
    expect(profile.entity_id).toBe("user_1");
    expect(profile.static).toHaveLength(1);
    expect(profile.memory_count).toBe(42);
  });
});

describe("health()", () => {
  it("should return health status", async () => {
    const client = createClient([
      mockResponse({ status: "ok", version: "0.5.0", checks: { postgres: "ok" } }),
    ]);
    const health = await client.health();
    expect(health.status).toBe("ok");
    expect(health.version).toBe("0.5.0");
  });
});

describe("error handling", () => {
  it("should throw EmeraldAuthError on 401", async () => {
    const client = createClient([
      mockResponse({ error_code: "AUTH_INVALID_KEY", message: "Invalid key" }, 401),
    ]);
    await expect(client.profile("user_1")).rejects.toThrow(EmeraldAuthError);
  });

  it("should throw EmeraldNotFoundError on 404", async () => {
    const client = createClient([
      mockResponse({ error_code: "MEMORY_NOT_FOUND", message: "Not found" }, 404),
    ]);
    await expect(client.getMemory("mem_x")).rejects.toThrow(EmeraldNotFoundError);
  });

  it("should throw EmeraldValidationError on 422 with field errors", async () => {
    const client = createClient([
      mockResponse({
        error_code: "VALIDATION_ERROR",
        message: "Validation failed",
        details: [{ field: "content", message: "Required" }],
      }, 422),
    ]);
    try {
      await client.add("", "user_1");
      expect.fail("Should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(EmeraldValidationError);
      const ve = e as EmeraldValidationError;
      expect(ve.fieldErrors.content).toBe("Required");
    }
  });

  it("should throw EmeraldRateLimitError on 429 with retry-after", async () => {
    const client = createClient([
      mockResponse({ error_code: "RATE_LIMITED", message: "Too many" }, 429, { "Retry-After": "30" }),
    ]);
    try {
      await client.search("test", "user_1");
      expect.fail("Should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(EmeraldRateLimitError);
      expect((e as EmeraldRateLimitError).retryAfter).toBe(30);
    }
  });

  it("should throw EmeraldServerError on 500 (after retries exhausted)", async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ error_code: "INTERNAL_ERROR", message: "Boom" }, 500));
    const client = new EmeraldClient({
      apiKey: "em_test",
      baseUrl: "http://test",
      maxRetries: 0,  // no retries for this test
      fetch: mockFetch as unknown as typeof fetch,
    });
    await expect(client.profile("user_1")).rejects.toThrow(EmeraldServerError);
  });

  it("should include errorCode on exceptions", async () => {
    const client = createClient([
      mockResponse({ error_code: "ENTITY_UNAUTHORIZED", message: "Nope" }, 403),
    ]);
    try {
      await client.profile("user_1");
    } catch (e) {
      expect((e as EmeraldError).errorCode).toBe("ENTITY_UNAUTHORIZED");
    }
  });

  it("should throw EmeraldNetworkError on fetch failure", async () => {
    const mockFetch = vi.fn(() => Promise.reject(new Error("Connection refused")));
    const client = new EmeraldClient({
      apiKey: "em_test",
      baseUrl: "http://test",
      maxRetries: 0,  // no retries
      fetch: mockFetch as unknown as typeof fetch,
    });
    await expect(client.health()).rejects.toThrow(EmeraldNetworkError);
  });
});

describe("retry logic", () => {
  it("should retry on 5xx up to maxRetries", async () => {
    const mockFetch = vi
      .fn()
      .mockRejectedValueOnce(new Error("Connection refused")) // attempt 0: network error
      .mockResolvedValueOnce(mockResponse({ error_code: "INTERNAL_ERROR" }, 503)) // attempt 1: 503
      .mockResolvedValueOnce(mockResponse({ status: "ok", version: "0.5.0", checks: {} })); // attempt 2: success

    const client = new EmeraldClient({
      apiKey: "em_test",
      baseUrl: "http://test",
      maxRetries: 3,
      timeout: 1000, // short timeout so backoff doesn't slow test
      fetch: mockFetch as unknown as typeof fetch,
    });

    // Override _backoff to be instant in tests
    (client as unknown as { _backoff: (n: number) => Promise<void> })._backoff = async () => {};

    const result = await client.health();
    expect(result.status).toBe("ok");
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it("should not retry uploads on network error", async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error("Connection refused"));
    const client = new EmeraldClient({
      apiKey: "em_test",
      baseUrl: "http://test",
      maxRetries: 2,
      fetch: mockFetch as unknown as typeof fetch,
    });

    const file = new File(["test"], "test.txt");
    await expect(client.upload(file, "user_1")).rejects.toThrow("Connection refused");
    expect(mockFetch).toHaveBeenCalledTimes(1); // no retries for upload
  });
});

describe("v1 format backward compatibility", () => {
  it("should parse v1 error format", async () => {
    const client = createClient([
      mockResponse({ error: { code: "NOT_FOUND", message: "old format" } }, 404),
    ]);
    await expect(client.getMemory("x")).rejects.toThrow("old format");
  });
});
