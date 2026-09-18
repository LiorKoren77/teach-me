import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "../api/client";

describe("apiFetch", () => {
  afterEach(() => vi.restoreAllMocks());

  it("adds the bearer token and parses json", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    const out = await apiFetch<{ ok: number }>("/api/x", async () => "tok", { method: "POST", body: "{}" });
    expect(out.ok).toBe(1);
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("throws ApiError with the backend detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "not your attempt" }), { status: 403 }));
    await expect(apiFetch("/api/x", async () => null)).rejects.toMatchObject<Partial<ApiError>>({ status: 403, detail: "not your attempt" });
  });
});
