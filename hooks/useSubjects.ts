"use client";
import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { listSources, listSubjects } from "@/lib/api/subjects";
import type { StudentSource, SubjectSummary } from "@/lib/api/types";
import { useApiError } from "./useApiError";

export function useSubjects() {
  const { getToken, isSignedIn } = useAuth();
  const [subjects, setSubjects] = useState<SubjectSummary[] | null>(null);
  const { error, fail } = useApiError();
  useEffect(() => {
    if (!isSignedIn) return;
    let cancelled = false;
    listSubjects(getToken)
      .then((rows) => {
        if (!cancelled) setSubjects(rows);
      })
      .catch((failure) => {
        if (!cancelled) fail(failure);
      });
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, getToken, fail]);
  return { subjects, error };
}

/** A subject's sources, read-only: the same backend concern, so the same module. */
export function useSources(subjectId: string) {
  const { getToken, isSignedIn } = useAuth();
  const [sources, setSources] = useState<StudentSource[] | null>(null);
  const { error, fail } = useApiError();
  useEffect(() => {
    if (!isSignedIn) return;
    let cancelled = false;
    listSources(subjectId, getToken)
      .then((rows) => {
        if (!cancelled) setSources(rows);
      })
      .catch((failure) => {
        if (!cancelled) fail(failure);
      });
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, subjectId, getToken, fail]);
  return { sources, error };
}
