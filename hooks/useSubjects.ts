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
    listSubjects(getToken).then(setSubjects).catch(fail);
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
    listSources(subjectId, getToken).then(setSources).catch(fail);
  }, [isSignedIn, subjectId, getToken, fail]);
  return { sources, error };
}
