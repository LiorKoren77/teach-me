import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useReexplainStream } from "../useReexplainStream";

const auth = { getToken: async () => "tok" };
const clerk = { redirectToSignIn: async () => undefined };
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth, useClerk: () => clerk }));

afterEach(() => vi.restoreAllMocks());

describe("useReexplainStream", () => {
  it("maps a refused stream from its JSON error body", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: "this round was already re-explained" }), {
          status: 409,
          headers: { "content-type": "application/json" },
        }),
    );
    const { result } = renderHook(() => useReexplainStream("att", 1, true));

    await waitFor(() => expect(result.current.error).toBe("conflict"));
    expect(result.current.streaming).toBe(false);
    expect(result.current.text).toBe("");
  });

  it("keeps the finished text of the round it was asked about", async () => {
    const body = ["event: delta", 'data: {"text":"because"}', "", "event: done", 'data: {"text":"because it cools","truncated":false}', "", ""].join("\n");
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    );
    const { result } = renderHook(() => useReexplainStream("att", 2, true));

    await waitFor(() => expect(result.current.finished).toBe(true));
    expect(result.current.text).toBe("because it cools");
    expect(result.current.error).toBeNull();
  });
});
