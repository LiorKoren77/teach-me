"use client";
import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { adminSources, adminSubjects, adminUsage } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/client";
import type { AdminSource, AdminSubject, UsageRow } from "@/lib/api/types";
import { useApiError } from "./useApiError";

/**
 * Read-only admin data: every subject, then the selected subject's sources and usage. The
 * backend enforces the admin role - a 403 here means the caller is signed in but not an admin,
 * so it is reported as `forbidden` rather than folded into `error`, letting the screen render a
 * plain refusal message instead of a generic failure.
 */
export function useAdmin() {
  const { getToken, isSignedIn } = useAuth();
  const [subjects, setSubjects] = useState<AdminSubject[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sources, setSources] = useState<AdminSource[] | null>(null);
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
    adminSources(selectedId, getToken)
      .then((rows) => {
        if (!cancelled) setSources(rows);
      })
      .catch((failure) => {
        if (!cancelled) fail(failure);
      });
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

  return { subjects, selectedId, sources, usage, forbidden, error, selectSubject };
}
