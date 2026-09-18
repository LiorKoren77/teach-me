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
import type { AdminJob, AdminSource, AdminSubject, AdminSubjectStatus } from "@/lib/api/types";
import { useApiError } from "./useApiError";

/** How often something still moving is asked about again. Ingestion steps are far slower. */
const POLL_MS = 3000;
/** The two source statuses that never change again on their own. */
const SETTLED = ["ready", "failed"];

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
}

const EMPTY: SubjectData = { id: null, sources: null, status: null, job: null, jobId: null };

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
  const [data, setData] = useState<SubjectData>(EMPTY);
  const [busy, setBusy] = useState(false);
  const { error, fail, clear } = useApiError();

  // Held in a ref so a caller that passes an inline function does not restart every effect.
  const changed = useRef(onSubjectChanged);
  useEffect(() => {
    changed.current = onSubjectChanged;
  }, [onSubjectChanged]);

  /** An answer applied only to the subject it was asked about; a late one for another is dropped. */
  const patch = useCallback((id: string, change: Partial<SubjectData>) => {
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
        if (!cancelled) setAccepted(capabilities.accepted_media_types);
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
    if (!ingesting) return;
    const timer = setInterval(() => void refreshSources(), POLL_MS);
    return () => clearInterval(timer);
  }, [ingesting, refreshSources]);

  // Generation is many jobs behind one; this follows the one that was started, and re-reads the
  // subject once it settles, which is when the status summary has something new to say.
  const jobId = current.jobId;
  useEffect(() => {
    if (!isSignedIn || !subjectId || !jobId) return;
    let cancelled = false;
    const tick = () => {
      adminJob(jobId, getToken)
        .then((next) => {
          if (cancelled) return;
          const finished = next.status === "done" || next.status === "failed";
          patch(subjectId, { job: next, jobId: finished ? null : jobId });
          if (!finished) return;
          void refreshSources();
          void refreshStatus();
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
  }, [isSignedIn, subjectId, jobId, getToken, patch, fail, refreshSources, refreshStatus]);

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
          return { ...base, sources: [...(base.sources ?? []), source], jobId: started };
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
        patch(subjectId, { jobId: started.job_id });
        await refreshSources();
      });
    },
    [subjectId, getToken, run, patch, refreshSources],
  );

  const generate = useCallback(() => {
    if (!subjectId) return;
    void run(async () => {
      const started = await generateSubject(subjectId, getToken);
      patch(subjectId, { jobId: started.job_id });
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
    sources: current.sources,
    status: current.status,
    job: current.job,
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
