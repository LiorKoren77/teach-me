"use client";
import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  adminCapabilities,
  adminJob,
  adminSources,
  adminSubjectStatus,
  deleteSource,
  generateSubject,
  publishSubject,
  reingestSource,
  unpublishSubject,
  uploadSource,
} from "@/lib/api/admin";
import type { AdminJob, AdminLanguageStatus, AdminSource, AdminSubject, AdminSubjectStatus, SourceStatus } from "@/lib/api/types";
import { useApiError } from "./useApiError";

/** How often something still moving is asked about again. Ingestion steps are far slower. */
const POLL_MS = 3000;
/** The two source statuses that never change again on their own. */
const SETTLED: SourceStatus[] = ["ready", "failed"];
/**
 * Upper bound on how many times a job is polled before giving up on it - about two minutes at
 * `POLL_MS`. A job stuck behind a crashed worker would otherwise be asked about forever for as
 * long as the admin screen stays open.
 */
export const MAX_JOB_POLL_TICKS = 40;

/** A language whose generation has not landed yet: not every part is ready, or a part failed and
 * the language has not otherwise settled. `publishable` on the status as a whole is the simpler
 * check once every language agrees, but a run can still be moving in one language while another
 * is already done. */
function languageStillGenerating(language: AdminLanguageStatus): boolean {
  return language.parts_ready < language.parts_total || (language.failed.length > 0 && !language.complete);
}

/**
 * Whether a subject's generation is still doing something the pane should keep watching for: the
 * `generate_subject` job itself only runs the outline and fans the parts out as jobs of their
 * own, so under the `vercel_function`/`sqs` runners that parent job is `done` long before every
 * part has actually generated. `publishable` is the simplest "nothing left to wait for" signal,
 * but is checked defensively against each language too, since a status read moments after the
 * parent job settles can still show `publishable: false` for reasons unrelated to this run.
 */
function subjectStillGenerating(status: AdminSubjectStatus): boolean {
  if (status.publishable) return false;
  return status.languages.some(languageStillGenerating);
}

/**
 * Everything read or written about one subject, tagged with the subject it belongs to. Holding
 * the id alongside the data is what lets a switch to another subject show nothing rather than
 * the previous one's sources for as long as the first request takes: anything tagged with a
 * different id is simply not this subject's.
 */
interface SubjectData {
  id: string | null;
  sources: AdminSource[] | null;
  status: AdminSubjectStatus | null;
  job: AdminJob | null;
  /** The job being followed; `null` once it is done or failed, which stops the polling. */
  jobId: string | null;
  /** True once the job poll hit `MAX_JOB_POLL_TICKS` without the job reaching done/failed. */
  jobStale: boolean;
}

const EMPTY: SubjectData = { id: null, sources: null, status: null, job: null, jobId: null, jobStale: false };

/**
 * Everything an admin does to one subject: upload, delete and re-ingest its sources, generate,
 * publish and unpublish it. The polling lives here rather than in `UploadPane` so the components
 * stay plain - while any source is still being ingested the list is re-read every few seconds,
 * and a job started by generate or re-ingest is followed until it is done or failed.
 *
 * `subjectId` of `null` means "not now" (no subject chosen, or the reader is not an admin), and
 * nothing is requested at all - which is how the learn screen can call this unconditionally, as
 * hooks require, without a student ever touching an admin route.
 */
export function useAdminActions(subjectId: string | null, onSubjectChanged?: (subject: AdminSubject) => void) {
  const { getToken, isSignedIn } = useAuth();
  const [acceptedMediaTypes, setAccepted] = useState<string[]>([]);
  // Infinite until the capabilities answer lands, so nothing is refused before the real cap is known.
  const [maxUploadBytes, setMaxUploadBytes] = useState<number>(Number.POSITIVE_INFINITY);
  const [data, setData] = useState<SubjectData>(EMPTY);
  const [busy, setBusy] = useState(false);
  const { error, fail, clear } = useApiError();

  // Held in a ref so a caller that passes an inline function does not restart every effect.
  const changed = useRef(onSubjectChanged);
  useEffect(() => {
    changed.current = onSubjectChanged;
  }, [onSubjectChanged]);

  // Held so a late answer asked about a subject that is no longer the one selected is dropped
  // outright rather than re-tagging the current state to it - a ref rather than `subjectId`
  // itself because the effects and callbacks below close over whichever value was current when
  // the request went out, while this always holds what is selected right now.
  const selected = useRef(subjectId);
  useEffect(() => {
    selected.current = subjectId;
  }, [subjectId]);

  /** An answer applied only to the subject currently selected; a late one for any other is dropped. */
  const patch = useCallback((id: string, change: Partial<SubjectData>) => {
    if (id !== selected.current) return;
    setData((previous) => ({ ...(previous.id === id ? previous : { ...EMPTY, id }), ...change }));
  }, []);

  const refreshSources = useCallback((): Promise<void> => {
    if (!isSignedIn || !subjectId) return Promise.resolve();
    return adminSources(subjectId, getToken).then(
      (rows) => patch(subjectId, { sources: rows }),
      (failure) => fail(failure),
    );
  }, [isSignedIn, subjectId, getToken, patch, fail]);

  const refreshStatus = useCallback((): Promise<void> => {
    if (!isSignedIn || !subjectId) return Promise.resolve();
    return adminSubjectStatus(subjectId, getToken).then(
      (next) => patch(subjectId, { status: next }),
      (failure) => fail(failure),
    );
  }, [isSignedIn, subjectId, getToken, patch, fail]);

  useEffect(() => {
    void refreshSources();
    void refreshStatus();
  }, [refreshSources, refreshStatus]);

  // A property of the deployment, not of the subject, but it is an admin route like the rest, so
  // it is only asked for once there is a subject to upload to.
  useEffect(() => {
    if (!isSignedIn || !subjectId) return;
    let cancelled = false;
    adminCapabilities(getToken)
      .then((capabilities) => {
        if (cancelled) return;
        setAccepted(capabilities.accepted_media_types);
        // Infinite when the payload carries no cap at all, same as before the answer lands - a
        // deployment ahead of this client's idea of the schema should not refuse every upload.
        setMaxUploadBytes(capabilities.max_upload_bytes ?? Number.POSITIVE_INFINITY);
      })
      .catch((failure) => {
        if (!cancelled) fail(failure);
      });
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, subjectId, getToken, fail]);

  // Only this subject's own answers are shown; anything still tagged with the previous one is not.
  const current = data.id === subjectId ? data : EMPTY;

  // Ingestion moves a source through its statuses in the background; the list is the progress.
  const ingesting = (current.sources ?? []).some((source) => !SETTLED.includes(source.status));
  useEffect(() => {
    if (!ingesting || !subjectId) return;
    let cancelled = false;
    let ticks = 0;
    const timer = setInterval(() => {
      ticks += 1;
      void refreshSources().then(() => {
        if (cancelled) return;
        // Same budget as a followed job: a source wedged behind a crashed worker would
        // otherwise be asked about for as long as the screen stays open.
        if (ticks >= MAX_JOB_POLL_TICKS) {
          patch(subjectId, { jobStale: true });
          clearInterval(timer);
        }
      });
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [ingesting, subjectId, refreshSources, patch]);

  // Generation is many jobs behind one; this follows the one that was started. Under the
  // vercel_function/sqs runners `generate_subject` itself is done long before every part has -
  // it only ran the outline and handed each part to a job of its own - so once the followed job
  // settles this keeps reading the subject's status on the same interval until every language is
  // ready, giving up the same way a stuck job does: `jobStale`, once its own tick budget runs out.
  const jobId = current.jobId;
  useEffect(() => {
    if (!isSignedIn || !subjectId || !jobId) return;
    let cancelled = false;
    let ticks = 0;
    // Flips once the followed job itself has settled; from then on each tick re-reads the
    // subject's status instead of the job, which has nothing left to say.
    let followingStatus = false;
    const pollStatus = () => {
      adminSubjectStatus(subjectId, getToken).then(
        (status) => {
          if (cancelled) return;
          patch(subjectId, { status });
          if (!subjectStillGenerating(status)) {
            patch(subjectId, { jobId: null });
            return;
          }
          // Gave up: a crashed or wedged worker would otherwise be polled for as long as the
          // screen stays open.
          if (ticks >= MAX_JOB_POLL_TICKS) {
            patch(subjectId, { jobId: null, jobStale: true });
          }
        },
        (failure) => {
          if (cancelled) return;
          patch(subjectId, { jobId: null });
          fail(failure);
        },
      );
    };
    const tick = () => {
      ticks += 1;
      if (followingStatus) {
        pollStatus();
        return;
      }
      adminJob(jobId, getToken)
        .then((next) => {
          if (cancelled) return;
          const finished = next.status === "done" || next.status === "failed";
          if (!finished) {
            // Gave up: a crashed or wedged worker would otherwise be polled for as long as the
            // screen stays open. The job's own state is kept so the last known status still shows.
            if (ticks >= MAX_JOB_POLL_TICKS) {
              patch(subjectId, { job: next, jobId: null, jobStale: true });
              return;
            }
            patch(subjectId, { job: next, jobId });
            return;
          }
          patch(subjectId, { job: next, jobStale: false });
          void refreshSources();
          followingStatus = true;
          ticks = 0; // a fresh budget for watching the parts the job only fanned out
          pollStatus();
        })
        .catch((failure) => {
          if (cancelled) return;
          patch(subjectId, { jobId: null });
          fail(failure);
        });
    };
    tick();
    const timer = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [isSignedIn, subjectId, jobId, getToken, patch, fail, refreshSources]);

  /** One action: the screen is busy for its duration and a failure becomes a translated message. */
  const run = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      clear();
      try {
        await action();
      } catch (failure) {
        fail(failure);
      } finally {
        setBusy(false);
      }
    },
    [clear, fail],
  );

  const upload = useCallback(
    (file: File) => {
      if (!subjectId) return;
      void run(async () => {
        const { job_id: started, ...source } = await uploadSource(subjectId, file, getToken);
        // Shown at once so the reader sees the file land; the poll above takes it from there.
        setData((previous) => {
          const base = previous.id === subjectId ? previous : { ...EMPTY, id: subjectId };
          return { ...base, sources: [...(base.sources ?? []), source], jobId: started, jobStale: false };
        });
      });
    },
    [subjectId, getToken, run],
  );

  const remove = useCallback(
    (sourceId: string) => {
      if (!subjectId) return;
      void run(async () => {
        await deleteSource(sourceId, getToken);
        setData((previous) =>
          previous.id === subjectId
            ? { ...previous, sources: (previous.sources ?? []).filter((row) => row.id !== sourceId) }
            : previous,
        );
        await refreshStatus();
      });
    },
    [subjectId, getToken, run, refreshStatus],
  );

  const reingest = useCallback(
    (sourceId: string) => {
      if (!subjectId) return;
      void run(async () => {
        const started = await reingestSource(sourceId, getToken);
        patch(subjectId, { jobId: started.job_id, jobStale: false });
        await refreshSources();
      });
    },
    [subjectId, getToken, run, patch, refreshSources],
  );

  const generate = useCallback(() => {
    if (!subjectId) return;
    void run(async () => {
      const started = await generateSubject(subjectId, getToken);
      patch(subjectId, { jobId: started.job_id, jobStale: false });
    });
  }, [subjectId, getToken, run, patch]);

  const publish = useCallback(() => {
    if (!subjectId) return;
    void run(async () => {
      changed.current?.(await publishSubject(subjectId, getToken));
      await refreshStatus();
    });
  }, [subjectId, getToken, run, refreshStatus]);

  const unpublish = useCallback(() => {
    if (!subjectId) return;
    void run(async () => {
      changed.current?.(await unpublishSubject(subjectId, getToken));
      await refreshStatus();
    });
  }, [subjectId, getToken, run, refreshStatus]);

  return {
    acceptedMediaTypes,
    maxUploadBytes,
    sources: current.sources,
    status: current.status,
    job: current.job,
    /** True once the job poll gave up on a job that never reached done/failed. */
    jobStale: current.jobStale,
    busy,
    error,
    /** The backend's word on it, which is what locks uploads and the per-source actions. */
    published: current.status?.state === "published",
    upload,
    remove,
    reingest,
    generate,
    publish,
    unpublish,
  };
}
