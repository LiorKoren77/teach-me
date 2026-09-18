import { auth } from "@clerk/nextjs/server";
import { AdminScreen } from "./AdminScreen";

// The proxy's prefix check is optimistic (see proxy.ts), so this page protects itself against a
// signed-out visitor the same way /learn does. The admin *role* is not checked here: the backend
// enforces it on every /api/admin/* route, and a 403 from those is what AdminScreen turns into
// the "admin role required" message.
export default async function AdminPage() {
  await auth.protect();
  return <AdminScreen />;
}
