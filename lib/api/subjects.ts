import { apiFetch, type TokenGetter } from "./client";
import type { StudentSource, SubjectSummary, SubjectView } from "./types";

export const listSubjects = (getToken: TokenGetter) => apiFetch<SubjectSummary[]>("/api/subjects", getToken);
export const openSubject = (id: string, getToken: TokenGetter) => apiFetch<SubjectView>(`/api/subjects/${id}`, getToken);
export const listSources = (id: string, getToken: TokenGetter) => apiFetch<StudentSource[]>(`/api/subjects/${id}/sources`, getToken);
export const pageImageUrl = (subjectId: string, globalIndex: number) => `/api/subjects/${subjectId}/pages/${globalIndex}/image`;
