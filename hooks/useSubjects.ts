"use client";
import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { listSources, listSubjects } from "@/lib/api/subjects";
import type { StudentSource, SubjectSummary } from "@/lib/api/types";

export function useSubjects() {
  const { getToken, isSignedIn } = useAuth();
  const [subjects, setSubjects] = useState<SubjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!isSignedIn) return;
    listSubjects(getToken).then(setSubjects).catch((e) => setError(String(e.message ?? e)));
  }, [isSignedIn, getToken]);
  return { subjects, error };
}

/** A subject's sources, read-only: the same backend concern, so the same module. */
export function useSources(subjectId: string) {
  const { getToken, isSignedIn } = useAuth();
  const [sources, setSources] = useState<StudentSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!isSignedIn) return;
    listSources(subjectId, getToken).then(setSources).catch((e) => setError(String(e.message ?? e)));
  }, [isSignedIn, subjectId, getToken]);
  return { sources, error };
}
