"use client";
import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { listSubjects } from "@/lib/api/subjects";
import type { SubjectSummary } from "@/lib/api/types";

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
