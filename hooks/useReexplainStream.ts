"use client";
import { useAuth } from "@clerk/nextjs";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useEffect, useState } from "react";
import { reexplainUrl } from "@/lib/api/learning";

type Stream = { key: string; text: string; finished: boolean; truncated: boolean; error: string | null };

const EMPTY: Stream = { key: "", text: "", finished: false, truncated: false, error: null };

/**
 * The re-explanation of one failed round, as server-sent events: `delta` events append, the
 * final `done` event replaces the text with the rendered version (glossary placeholders
 * resolved) and says whether the model was cut off at its token ceiling.
 *
 * The backend generates the whole thing before it sends a byte, so there is a wait with nothing
 * to show: `waiting` is true until the first event arrives. State is keyed by attempt and round
 * - one attempt re-explains once per failed round - so a new round starts from empty while a
 * finished one keeps its text after the stream is closed.
 */
export function useReexplainStream(attemptId: string | null, roundNo: number | null, enabled: boolean) {
  const { getToken } = useAuth();
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
              setStream({ ...EMPTY, key, finished: true, error: event.data || "stream failed" });
            }
          },
          onerror(failure) {
            throw failure; // One attempt only: fetchEventSource would otherwise retry forever.
          },
        });
      } catch (failure) {
        if (controller.signal.aborted) return;
        const detail = failure instanceof Error ? failure.message : String(failure);
        setStream((previous) => (previous.key === key && previous.finished ? previous : { ...EMPTY, key, finished: true, error: detail }));
      }
    })();
    return () => controller.abort();
  }, [attemptId, key, enabled, getToken]);

  const mine = stream.key === key && key !== "";
  const text = mine ? stream.text : "";
  const finished = mine && stream.finished;
  return {
    text,
    finished,
    truncated: mine && stream.truncated,
    error: mine ? stream.error : null,
    streaming: enabled && !finished,
    waiting: enabled && !finished && text === "",
  };
}
