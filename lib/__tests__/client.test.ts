import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, apiUpload } from "../api/client";

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

describe("apiUpload", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends the file as multipart and leaves the content type to the browser", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "s1", job_id: "j1" }), { status: 200 }));
    const file = new File(["%PDF-1.4"], "book.pdf", { type: "application/pdf" });

    const out = await apiUpload<{ id: string; job_id: string }>("/api/admin/subjects/x/sources", file, async () => "tok");

    expect(out.job_id).toBe("j1");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    // A Content-Type set here would lose the multipart boundary the body was built with.
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");
    const body = init.body as FormData;
    expect((body.get("file") as File).name).toBe("book.pdf");
  });
});
