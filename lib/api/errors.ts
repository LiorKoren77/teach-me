import { ApiError } from "./client";

/** The i18n key an API failure is shown to the reader as; `lib/i18n.ts` holds the messages. */
export type ErrorKey =
  | "unauthorized"
  | "forbidden"
  | "notFound"
  | "conflict"
  | "payloadTooLarge"
  | "unsupportedType"
  | "rateLimited"
  | "unknown";

/**
 * One mapping from a failed request to something a reader can act on. The `detail` the API sends
 * is written for whoever reads the logs, not for a student mid-lesson, and it is never
 * translated, so it belongs in `console.debug` while the reader gets the message for this key.
 */
export function errorKeyOf(failure: unknown): ErrorKey {
  const status = failure instanceof ApiError ? failure.status : 0;
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "notFound";
  if (status === 409) return "conflict";
  if (status === 413) return "payloadTooLarge";
  if (status === 415) return "unsupportedType";
  if (status === 429) return "rateLimited";
  return "unknown";
}
