import { clerkMiddleware } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";

// Next 16 renamed Middleware to Proxy; the file is proxy.ts and the export is the default
// (see node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md).
//
// `/` is public - it offers the sign-in - and `/api` is left out of the matcher below: the
// Python backend verifies its own Clerk JWTs, and in development next.config.ts rewrites
// `/api` to it.
//
// This is an optimistic check only. Clerk Core 3 deprecated `createRouteMatcher` because
// path matching here can diverge from how Next.js routes a request, so every page under
// /learn and /admin must also check for itself (`await auth.protect()`, and the admin role
// for /admin) rather than trusting this file.
const PROTECTED_PREFIXES = ["/learn", "/admin"];

function isProtected(request: NextRequest): boolean {
  const path = request.nextUrl.pathname;
  return PROTECTED_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export default clerkMiddleware(async (auth, request) => {
  if (isProtected(request)) await auth.protect();
});

export const config = {
  // Everything but Next's own assets, the API and files with an extension.
  matcher: ["/((?!_next|api|.*\\..*).*)"],
};
