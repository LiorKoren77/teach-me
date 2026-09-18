/**
 * The role the backend reads out of a Clerk session token: a top-level `role` claim, which the
 * session-token template maps from `public_metadata.role`, and the metadata itself when the
 * template has not been given that shorthand (see "Authentication" in the README). Anything
 * else, including a token with no claim at all, is a student.
 *
 * This only decides what is worth offering the reader - every admin route is enforced by the
 * API, which verifies the same claim itself.
 */
export function isAdmin(claims: unknown): boolean {
  const token = (claims ?? {}) as { role?: unknown; public_metadata?: { role?: unknown } | null };
  const role = token.role ?? token.public_metadata?.role;
  return role === "admin";
}
