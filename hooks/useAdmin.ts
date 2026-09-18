"use client";
import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { adminSubjects, adminUsage } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/client";
import type { AdminSubject, UsageRow } from "@/lib/api/types";
import { useApiError } from "./useApiError";

/**
 * The admin screen's own data: every subject, and the selected subject's usage. The sources and
 * the tutorial status belong to `useAdminActions`, which polls them while anything is moving, so
 * they are not read twice here. The backend enforces the admin role - a 403 here means the
 * caller is signed in but not an admin, so it is reported as `forbidden` rather than folded into
 * `error`, letting the screen render a plain refusal message instead of a generic failure.
 */
export function useAdmin() {
  const { getToken, isSignedIn } = useAuth();
  const [subjects, setSubjects] = useState<AdminSubject[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [usage, setUsage] = useState<UsageRow[] | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const { error, fail: report } = useApiError();

  const fail = useCallback(
    (failure: unknown) => {
      if (failure instanceof ApiError && failure.status === 403) setForbidden(true);
      else report(failure);
    },
    [report],
  );

  useEffect(() => {
    if (!isSignedIn) return;
    let cancelled = false;
    adminSubjects(getToken)
      .then((rows) => {
        if (cancelled) return;
        setSubjects(rows);
        setSelectedId((current) => current ?? rows[0]?.id ?? null);
      })
      .catch((failure) => {
        if (!cancelled) fail(failure);
      });
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, getToken, fail]);

  useEffect(() => {
    if (!isSignedIn || !selectedId) return;
    let cancelled = false;
    adminUsage(selectedId, getToken)
      .then((rows) => {
        if (!cancelled) setUsage(rows);
      })
      .catch((failure) => {
        if (!cancelled) fail(failure);
      });
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, selectedId, getToken, fail]);

  const selectSubject = useCallback((id: string) => setSelectedId(id), []);
  /** Publishing answers with the updated subject, so the list need not be read again for it. */
  const replaceSubject = useCallback(
    (subject: AdminSubject) => setSubjects((rows) => (rows ?? []).map((row) => (row.id === subject.id ? subject : row))),
    [],
  );

  return { subjects, selectedId, usage, forbidden, error, selectSubject, replaceSubject };
}
