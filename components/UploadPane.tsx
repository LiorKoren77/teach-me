"use client";

import { useId, useRef, useState } from "react";
import { SourceRow } from "@/components/SourceRow";
import type { AdminSource } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

/**
 * The admin's side of a subject's sources: pick a file, upload it, then watch what ingestion
 * makes of each one. It fetches nothing - the caller's hook owns the upload, the deletions and
 * the polling that keeps `sources` moving while anything is still being ingested.
 *
 * `acceptedMediaTypes` comes from the backend's capabilities rather than a list hard-coded here,
 * so the picker offers exactly what `SourceService` will accept; the backend still refuses an
 * unaccepted type with 415, since a file picker's `accept` is only a hint.
 */
export function UploadPane({
  sources,
  acceptedMediaTypes,
  published,
  busy,
  strings,
  onUpload,
  onDelete,
  onReingest,
  confirm,
}: {
  sources: AdminSource[];
  acceptedMediaTypes: string[];
  published: boolean;
  busy: boolean;
  strings: Strings;
  onUpload: (file: File) => void;
  onDelete: (sourceId: string) => void;
  onReingest: (sourceId: string) => void;
  confirm?: (message: string) => boolean;
}) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [chosen, setChosen] = useState<File | null>(null);

  const send = () => {
    if (!chosen) return;
    onUpload(chosen);
    // The same file picked twice in a row fires no change event unless the input is cleared, and
    // re-uploading the same file is a real thing to want after a failed ingestion.
    setChosen(null);
    if (input.current) input.current.value = "";
  };

  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <h2 className="text-sm font-medium text-stone-900">{strings.uploadSources}</h2>

      <div className="mt-2 flex flex-col gap-2">
        <label htmlFor={inputId} className="text-xs text-stone-600">
          {strings.chooseFile}
        </label>
        <input
          id={inputId}
          ref={input}
          type="file"
          accept={acceptedMediaTypes.join(",")}
          disabled={published || busy}
          onChange={(event) => setChosen(event.target.files?.[0] ?? null)}
          className="text-sm text-stone-700 file:me-2 file:rounded file:border file:border-stone-300 file:bg-stone-50 file:px-2 file:py-1 file:text-xs"
        />
        <p className="text-xs text-stone-500">{strings.acceptedTypes(acceptedMediaTypes.join(", "))}</p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={send}
            disabled={published || busy || chosen === null}
            className="rounded border border-stone-300 px-3 py-1 text-sm hover:border-stone-500 disabled:opacity-50"
          >
            {strings.upload}
          </button>
          {busy ? <span className="text-xs text-stone-500">{strings.uploading}</span> : null}
        </div>
        {published ? <p className="text-xs text-stone-600">{strings.uploadLocked}</p> : null}
      </div>

      {sources.length === 0 ? (
        <p className="mt-3 text-sm text-stone-500">{strings.noSources}</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {sources.map((source) => (
            <SourceRow
              key={source.id}
              source={source}
              published={published}
              strings={strings}
              onDelete={onDelete}
              onReingest={onReingest}
              confirm={confirm}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
