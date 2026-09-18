import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_JOB_POLL_TICKS, useAdminActions } from "../useAdminActions";
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

  it("stops polling a job that never settles once the tick bound is hit, and marks it stale", async () => {
    stubApi();
    const { result } = renderHook(() => useAdminActions("subj"));
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    await act(async () => {
      result.current.upload(new File(["%PDF-1.4"], "next.pdf", { type: "application/pdf" }));
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(result.current.job?.id).toBe("j2"));
    expect(result.current.jobStale).toBe(false);

    const jobCallsBefore = calls.filter((call) => call.includes("/api/admin/jobs/")).length;
    // One tick already fired above; the job endpoint keeps answering "running" forever, so the
    // remaining ticks up to the bound should be the last ones asked.
    await act(async () => {
      await vi.advanceTimersByTimeAsync((MAX_JOB_POLL_TICKS - 1) * 3000);
    });
    await waitFor(() => expect(result.current.jobStale).toBe(true));
    // The last known status is kept even though polling stopped.
    expect(result.current.job?.status).toBe("running");
    const jobCallsAtBound = calls.filter((call) => call.includes("/api/admin/jobs/")).length;
    expect(jobCallsAtBound - jobCallsBefore).toBe(MAX_JOB_POLL_TICKS - 1);

    // Polling has stopped: waiting well past another poll interval asks the job endpoint no more.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(calls.filter((call) => call.includes("/api/admin/jobs/")).length).toBe(jobCallsAtBound);
  });

  it("clears normally when a job finishes before the tick bound", async () => {
    const fetchMock = stubApi();
    const { result } = renderHook(() => useAdminActions("subj"));
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    await act(async () => {
      result.current.upload(new File(["%PDF-1.4"], "next.pdf", { type: "application/pdf" }));
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(result.current.job?.id).toBe("j2"));

    sources = [source({ status: "ready", page_count: 2 }), source({ id: "s2", filename: "next.pdf", status: "ready" })];
    fetchMock.mockImplementation(async (input, init) => {
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
      if (url.endsWith("/sources")) return json(sources);
      if (url.includes("/api/admin/jobs/")) return json({ id: "j2", kind: "ingest_source", status: "done", attempts: 1, error: null });
      throw new Error(`unexpected request: ${method} ${url}`);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    await waitFor(() => expect(result.current.job?.status).toBe("done"));
    expect(result.current.jobStale).toBe(false);

    // Finishing stops the poll well under the bound; nothing more is asked of the job endpoint.
    const jobCallsAtFinish = calls.filter((call) => call.includes("/api/admin/jobs/")).length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(calls.filter((call) => call.includes("/api/admin/jobs/")).length).toBe(jobCallsAtFinish);
  });
});
