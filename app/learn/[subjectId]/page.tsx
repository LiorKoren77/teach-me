import { auth } from "@clerk/nextjs/server";
import { LearnScreen } from "./LearnScreen";

// The proxy's prefix check is optimistic (Clerk Core 3 deprecated route-matcher protection
// because matching here can diverge from routing), so the page protects itself: a signed-out
// visitor is redirected to sign-in before any of this renders.
export default async function LearnPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = await params;
  await auth.protect();
  return <LearnScreen subjectId={subjectId} />;
}
