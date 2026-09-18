import type { AdminJob, AdminSubjectStatus } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

/**
 * The same summary `teachme tutorial status` prints, with the three things an admin does with a
 * subject next to it. Publish is disabled unless the backend says some outline version is
 * complete in every enabled language (`publishable`), which is the one rule the reader cannot
 * work out from the numbers alone. The job line is whatever the caller's hook is currently
 * polling - generation is many jobs, so this is a sign of life, not a progress bar.
 */
export function SubjectActions({
  status,
  job,
  jobStale,
  busy,
  strings,
  onGenerate,
  onPublish,
  onUnpublish,
}: {
  status: AdminSubjectStatus | null;
  job: AdminJob | null;
  /** True once the poll gave up on `job` without it reaching done/failed. */
  jobStale: boolean;
  busy: boolean;
  strings: Strings;
  onGenerate: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
}) {
  const published = status?.state === "published";
  const button = "rounded border border-stone-300 px-3 py-1 text-sm hover:border-stone-500 disabled:opacity-50";

  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <h2 className="text-sm font-medium text-stone-900">{strings.subjectActions}</h2>

      {status ? (
        <div className="mt-2 flex flex-col gap-1 text-sm text-stone-700">
          <span className="flex flex-wrap gap-x-4 text-xs text-stone-600">
            <span>{strings.adminState[status.state] ?? status.state}</span>
            <span>{strings.adminVersion(status.outline_version)}</span>
            <span>{strings.publishedVersion(status.published_version)}</span>
          </span>
          <ul className="flex flex-col gap-1">
            {status.languages.map((row) => (
              <li key={row.language} className="flex flex-wrap gap-x-3 text-xs text-stone-600">
                <span className="font-medium text-stone-800">{row.language}</span>
                <span>{strings.partsReady(row.parts_ready, row.parts_total)}</span>
                <span>{strings.questionsReady(row.questions)}</span>
                {row.failed.length === 0 ? null : (
                  <span className="text-red-700">{strings.failedParts(row.failed.join(", "))}</span>
                )}
              </li>
            ))}
          </ul>
          <span className="text-xs text-stone-600">
            {status.publishable && status.publishable_version !== null
              ? strings.publishable(status.publishable_version)
              : strings.notPublishable}
          </span>
        </div>
      ) : null}

      {job ? (
        <p className="mt-2 text-xs text-stone-600">
          {strings.jobLine(strings.jobKind[job.kind] ?? job.kind, strings.jobStatus[job.status] ?? job.status)}
        </p>
      ) : null}
      {jobStale ? <p className="mt-1 text-xs text-amber-700">{strings.jobStale}</p> : null}
      {job?.error ? <p className="mt-1 text-xs text-red-700">{job.error}</p> : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onGenerate} disabled={busy || published} className={button}>
          {strings.generate}
        </button>
        <button type="button" onClick={onPublish} disabled={busy || published || !status?.publishable} className={button}>
          {strings.publish}
        </button>
        <button type="button" onClick={onUnpublish} disabled={busy || !published} className={button}>
          {strings.unpublish}
        </button>
      </div>
    </section>
  );
}
