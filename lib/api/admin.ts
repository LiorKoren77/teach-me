import { apiFetch, type TokenGetter } from "./client";
import type { AdminSource, AdminSubject, UsageRow } from "./types";

export const adminSubjects = (getToken: TokenGetter) => apiFetch<AdminSubject[]>("/api/admin/subjects", getToken);
export const adminSources = (id: string, getToken: TokenGetter) => apiFetch<AdminSource[]>(`/api/admin/subjects/${id}/sources`, getToken);
export const adminUsage = (subjectId: string | null, getToken: TokenGetter) =>
  apiFetch<UsageRow[]>(`/api/admin/usage${subjectId ? `?subject_id=${subjectId}` : ""}`, getToken);
