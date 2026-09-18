import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAdminActions } from "../useAdminActions";
import type { AdminSource } from "@/lib/api/types";

const auth = { getToken: async () => "tok", isSignedIn: true };
const clerk = { redirectToSignIn: async () => undefined };
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth, useClerk: () => clerk }));

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

const source = (over: Partial<AdminSource> = {}): AdminSource => ({
  id: "s1", filename: "book.pdf", media_type: "application/pdf", status: "extracting",
  page_count: null, detected_language: null, error: null, ...over,
});

let sources: AdminSource[];
let calls: string[];

function stubApi() {
  sources = [source()];
  calls = [];
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url}`);
    if (url.endsWith("/api/admin/capabilities")) return json({ accepted_media_types: ["application/pdf"] });
    if (url.endsWith("/status")) {
      return json({
        state: "draft", outline_version: null, published_version: null, parts_total: 0,
        languages: [], publishable: false, publishable_version: null,
      });
    }
    if (url.endsWith("/sources") && method === "POST") return json({ ...source({ id: "s2", filename: "next.pdf" }), job_id: "j2" });
    if (url.endsWith("/sources")) return json(sources);
    if (url.includes("/api/admin/jobs/")) return json({ id: "j2", kind: "ingest_source", status: "running", attempts: 1, error: null });
    throw new Error(`unexpected request: ${method} ${url}`);
  });
}

const sourceReads = () => calls.filter((call) => call.startsWith("GET") && call.endsWith("/sources")).length;

describe("useAdminActions", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("requests nothing at all without a subject", async () => {
    stubApi();
    const { result } = renderHook(() => useAdminActions(null));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(calls).toEqual([]);
    expect(result.current.sources).toBeNull();
    expect(result.current.acceptedMediaTypes).toEqual([]);
  });

  it("reads the capabilities, the sources and the status, then polls until nothing is moving", async () => {
    stubApi();
    const { result } = renderHook(() => useAdminActions("subj"));

    await waitFor(() => expect(result.current.sources).toHaveLength(1));
    expect(result.current.acceptedMediaTypes).toEqual(["application/pdf"]);
    expect(result.current.published).toBe(false);

    // Still extracting, so the list is read again on the next tick.
    const first = sourceReads();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await waitFor(() => expect(sourceReads()).toBeGreaterThan(first));

    sources = [source({ status: "ready", page_count: 2, detected_language: "en" })];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await waitFor(() => expect(result.current.sources?.[0].status).toBe("ready"));

    // Everything has settled, so the polling stops rather than running for as long as the page is open.
    const settled = sourceReads();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(12000);
    });
    expect(sourceReads()).toBe(settled);
  });

  it("shows an uploaded file at once and follows the job it started", async () => {
    stubApi();
    const { result } = renderHook(() => useAdminActions("subj"));
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    await act(async () => {
      result.current.upload(new File(["%PDF-1.4"], "next.pdf", { type: "application/pdf" }));
      await vi.advanceTimersByTimeAsync(0);
    });

    await waitFor(() => expect(result.current.sources?.map((row) => row.filename)).toContain("next.pdf"));
    // The optimistic row carries the source, never the job id the upload answered with.
    expect(result.current.sources?.some((row) => "job_id" in row)).toBe(false);
    await waitFor(() => expect(result.current.job?.id).toBe("j2"));
  });
});
