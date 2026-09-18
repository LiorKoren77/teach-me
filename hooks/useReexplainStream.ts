"use client";
import { useAuth } from "@clerk/nextjs";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { reexplainUrl } from "@/lib/api/learning";
import { useApiErrorReport } from "./useApiError";

type Stream = { key: string; text: string; finished: boolean; truncated: boolean; error: ErrorKey | null };

const EMPTY: Stream = { key: "", text: "", finished: false, truncated: false, error: null };

/**
 * The re-explanation of one failed round, as server-sent events: `delta` events append, the
 * final `done` event replaces the text with the rendered version (glossary placeholders
 * resolved) and says whether the model was cut off at its token ceiling.
 *
 * State is keyed by attempt and round - one attempt re-explains once per failed round - so a new
 * round starts from empty, while the text of a finished one stays readable after the stream is
 * closed, including through the round that follows it.
 */
export function useReexplainStream(attemptId: string | null, roundNo: number | null, enabled: boolean) {
  const { getToken } = useAuth();
  const report = useApiErrorReport();
  const [stream, setStream] = useState<Stream>(EMPTY);
  const key = attemptId && roundNo !== null ? `${attemptId}#${roundNo}` : "";

  useEffect(() => {
    if (!enabled || !attemptId || !key) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = await getToken();
        if (controller.signal.aborted) return;
        await fetchEventSource(reexplainUrl(attemptId), {
          signal: controller.signal,
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          // The tab can be hidden while Opus works; closing the stream then would only make the
          // student wait for it twice.
          openWhenHidden: true,
          async onopen(response) {
            if (response.ok) return;
            // A refused stream carries the same JSON error body as any other route, so it is
            // turned back into an ApiError and shown the way the rest of them are.
            let detail = response.statusText;
            try {
              const body = await response.json();
              if (typeof body?.detail === "string") detail = body.detail;
            } catch {
              /* not json */
            }
            throw new ApiError(response.status, detail);
          },
          onmessage(event) {
            if (event.event === "delta") {
              const chunk = (JSON.parse(event.data) as { text?: string }).text ?? "";
              setStream((previous) =>
                previous.key === key ? { ...previous, text: previous.text + chunk } : { ...EMPTY, key, text: chunk },
              );
            } else if (event.event === "done") {
              const payload = JSON.parse(event.data) as { text?: string; truncated?: boolean };
              setStream({ key, text: payload.text ?? "", finished: true, truncated: payload.truncated === true, error: null });
            } else if (event.event === "error") {
              console.debug("re-explanation stream failed", event.data);
              setStream({ ...EMPTY, key, finished: true, error: "unknown" });
            }
          },
          onerror(failure) {
            throw failure; // One attempt only: fetchEventSource would otherwise retry forever.
          },
        });
      } catch (failure) {
        if (controller.signal.aborted) return;
        const mapped = report(failure);
        setStream((previous) => (previous.key === key && previous.finished ? previous : { ...EMPTY, key, finished: true, error: mapped }));
      }
    })();
    return () => controller.abort();
  }, [attemptId, key, enabled, getToken, report]);

  const mine = stream.key === key && key !== "";
  const finished = mine && stream.finished;
  return {
    text: mine ? stream.text : "",
    finished,
    truncated: mine && stream.truncated,
    error: mine ? stream.error : null,
    streaming: enabled && !finished,
  };
}
