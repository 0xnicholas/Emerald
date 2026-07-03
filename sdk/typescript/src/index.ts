/**
 * Emerald TypeScript SDK
 *
 * Four core methods (AGENTS.md): add, search, profile, upload.
 *
 * @example
 * ```ts
 * import { EmeraldClient } from "@emerald/sdk";
 *
 * const client = new EmeraldClient({ apiKey: "em_xxx" });
 * const result = await client.add("user likes TypeScript", "user_123");
 * const profile = await client.profile("user_123");
 * ```
 *
 * @packageDocumentation
 */

export { EmeraldClient } from "./client.js";
export type { EmeraldClientConfig } from "./client.js";

export {
  EmeraldAuthError,
  EmeraldError,
  EmeraldNetworkError,
  EmeraldNotFoundError,
  EmeraldRateLimitError,
  EmeraldServerError,
  EmeraldValidationError,
} from "./exceptions.js";

export type {
  AddOptions,
  AddResult,
  HealthStatus,
  PipelineStatus,
  Profile,
  ProfileFact,
  SearchOptions,
  SearchResult,
  SearchResults,
  UploadOptions,
} from "./models.js";

export { SDK_VERSION } from "./version.js";
