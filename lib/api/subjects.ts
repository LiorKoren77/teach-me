import { apiFetch, apiFetchBlob, type TokenGetter } from "./client";
import type { StudentSource, SubjectSummary, SubjectView } from "./types";

export const listSubjects = (getToken: TokenGetter) => apiFetch<SubjectSummary[]>("/api/subjects", getToken);
export const openSubject = (id: string, getToken: TokenGetter) => apiFetch<SubjectView>(`/api/subjects/${id}`, getToken);
export const listSources = (id: string, getToken: TokenGetter) => apiFetch<StudentSource[]>(`/api/subjects/${id}/sources`, getToken);

// The page image is bytes behind the same bearer guard as everything else, so it is fetched
// rather than pointed at from an <img src>, which could not carry the token.
export const pageImage = (subjectId: string, globalIndex: number, getToken: TokenGetter) =>
  apiFetchBlob(`/api/subjects/${subjectId}/pages/${globalIndex}/image`, getToken);
