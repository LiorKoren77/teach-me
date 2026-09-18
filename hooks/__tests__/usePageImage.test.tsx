import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePageImages } from "../usePageImage";

// One object for every render: the hook refetches when `getToken` changes identity, as the
// other hooks in this app do.
const auth = { getToken: async () => "tok", isSignedIn: true };
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth }));

const created: string[] = [];
const revoked: string[] = [];

beforeEach(() => {
  created.length = 0;
  revoked.length = 0;
  URL.createObjectURL = (() => {
    const url = `blob:page-${created.length}`;
    created.push(url);
    return url;
  }) as typeof URL.createObjectURL;
  URL.revokeObjectURL = ((url: string) => {
    revoked.push(url);
  }) as typeof URL.revokeObjectURL;
});

afterEach(() => vi.restoreAllMocks());

function pngResponse() {
  return new Response("png-bytes", { status: 200, headers: { "content-type": "image/png" } });
}

describe("usePageImages", () => {
  it("fetches each page with the bearer token and yields an object url", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => pngResponse());
    const { result } = renderHook(() => usePageImages("s1", [12]));

    await waitFor(() => expect(result.current[12]).toBe("blob:page-0"));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/subjects/s1/pages/12/image");
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
  });

  it("revokes the object url when the pane moves on", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => pngResponse());
    const { result, unmount } = renderHook(() => usePageImages("s1", [3]));

    await waitFor(() => expect(result.current[3]).toBe("blob:page-0"));
    unmount();
    expect(revoked).toEqual(["blob:page-0"]);
  });

  it("leaves a page without a url when the fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("nope", { status: 401 }));
    const { result } = renderHook(() => usePageImages("s1", [7]));

    await waitFor(() => expect(result.current).toHaveProperty("7"));
    expect(result.current[7]).toBeNull();
    expect(created).toEqual([]);
  });
});
