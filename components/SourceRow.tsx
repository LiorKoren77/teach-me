import type { AdminSource } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

/**
 * One uploaded source with what ingestion has made of it, and - while the subject is still a
 * draft - the two things that can be done to it. Both are destructive (delete drops everything
 * indexed from the file; re-ingest throws the extraction away and starts over), so both go
 * through `confirm`, which is a prop rather than a direct `window.confirm` call so a test can
 * answer it without a browser dialog.
 *
 * A published subject's sources are locked by the backend, so the buttons are not rendered at
 * all rather than rendered disabled: there is nothing here for the reader to wait for.
 */
export function SourceRow({
  source,
  published,
  strings,
  onDelete,
  onReingest,
  confirm = (message: string) => window.confirm(message),
}: {
  source: AdminSource;
  published: boolean;
  strings: Strings;
  onDelete: (sourceId: string) => void;
  onReingest: (sourceId: string) => void;
  confirm?: (message: string) => boolean;
}) {
  const ask = (message: string, run: () => void) => {
    if (confirm(message)) run();
  };

  return (
    <li className="flex flex-col gap-1 rounded border border-stone-200 px-3 py-2 text-sm text-stone-700">
      <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="break-words font-medium">{source.filename}</span>
        {/* The API sends the enum value; an unknown one is shown as it came. */}
        <span className="text-xs text-stone-600">{strings.sourceStatus[source.status] ?? source.status}</span>
      </span>
      <span className="flex flex-wrap gap-x-3 text-xs text-stone-500">
        {source.page_count === null ? null : <span>{strings.pageCount(source.page_count)}</span>}
        {source.detected_language === null ? null : <span>{strings.detectedLanguage(source.detected_language)}</span>}
      </span>
      {source.error ? <span className="text-xs text-red-700">{source.error}</span> : null}
      {published ? null : (
        <span className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={() => ask(strings.confirmReingest(source.filename), () => onReingest(source.id))}
            className="rounded border border-stone-300 px-2 py-1 text-xs hover:border-stone-500"
          >
            {strings.reingestSource}
          </button>
          <button
            type="button"
            onClick={() => ask(strings.confirmDelete(source.filename), () => onDelete(source.id))}
            className="rounded border border-stone-300 px-2 py-1 text-xs text-red-700 hover:border-red-400"
          >
            {strings.deleteSource}
          </button>
        </span>
      )}
    </li>
  );
}
