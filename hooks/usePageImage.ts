"use client";
import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { pageImage } from "@/lib/api/subjects";

type Fetched = { key: string; urls: Record<number, string | null> };

const EMPTY: Record<number, string | null> = {};

/**
 * The page images behind the figure thumbnails. The endpoint accepts a bearer token only, and an
 * `<img src>` cannot send one, so every page is fetched through the authenticated client and
 * handed to the browser as an object URL. A page maps to its URL once it has arrived, and to
 * `null` while it is on the way or after it failed; every URL made here is revoked when the set
 * of pages changes or the pane goes away, so none outlives the part it belongs to.
 *
 * One hook for the whole list, keyed by it: the number of pages varies per part, and a hook
 * cannot be called in a loop.
 */
export function usePageImages(subjectId: string, pages: number[]): Record<number, string | null> {
  const { getToken, isSignedIn } = useAuth();
  const [fetched, setFetched] = useState<Fetched>({ key: "", urls: {} });
  const key = `${subjectId}#${pages.join(",")}`;

  useEffect(() => {
    if (!isSignedIn || pageList(key).length === 0) return;
    let cancelled = false;
    const made: string[] = [];
    const store = (page: number, url: string | null) =>
      setFetched((previous) => (previous.key === key ? { key, urls: { ...previous.urls, [page]: url } } : { key, urls: { [page]: url } }));
    void (async () => {
      for (const page of pageList(key)) {
        try {
          const blob = await pageImage(subjectId, page, getToken);
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          made.push(url);
          store(page, url);
        } catch {
          if (cancelled) return;
          store(page, null);
        }
      }
    })();
    return () => {
      cancelled = true;
      for (const url of made) URL.revokeObjectURL(url);
    };
  }, [subjectId, key, isSignedIn, getToken]);

  // Anything fetched for an earlier list has been revoked by the cleanup above, so it is not
  // offered here even though it is still in state.
  return fetched.key === key ? fetched.urls : EMPTY;
}

function pageList(key: string): number[] {
  const pages = key.slice(key.indexOf("#") + 1);
  return pages === "" ? [] : pages.split(",").map(Number);
}
