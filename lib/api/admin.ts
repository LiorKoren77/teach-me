import { apiFetch, apiSend, apiUpload, type TokenGetter } from "./client";
import type {
  AdminCapabilities,
  AdminJob,
  AdminJobRef,
  AdminSource,
  AdminSubject,
  AdminSubjectStatus,
  AdminUpload,
  UsageRow,
} from "./types";

const subject = (id: string) => `/api/admin/subjects/${encodeURIComponent(id)}`;
const source = (id: string) => `/api/admin/sources/${encodeURIComponent(id)}`;

export const adminSubjects = (getToken: TokenGetter) => apiFetch<AdminSubject[]>("/api/admin/subjects", getToken);
export const adminSources = (id: string, getToken: TokenGetter) => apiFetch<AdminSource[]>(`${subject(id)}/sources`, getToken);
export const adminUsage = (subjectId: string | null, getToken: TokenGetter) =>
  apiFetch<UsageRow[]>(`/api/admin/usage${subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : ""}`, getToken);

/** What the file picker may offer; read once, since it is a property of the deployment. */
export const adminCapabilities = (getToken: TokenGetter) => apiFetch<AdminCapabilities>("/api/admin/capabilities", getToken);
/** The same numbers `teachme tutorial status` prints, including whether the subject can publish. */
export const adminSubjectStatus = (id: string, getToken: TokenGetter) => apiFetch<AdminSubjectStatus>(`${subject(id)}/status`, getToken);

// Uploading answers with the registered source and the ingestion job queued for it; the pane
// follows that source's own status rather than the job, since ingestion is resumable and may
// take several job runs.
export const uploadSource = (id: string, file: File, getToken: TokenGetter) => apiUpload<AdminUpload>(`${subject(id)}/sources`, file, getToken);
export const deleteSource = (id: string, getToken: TokenGetter) => apiSend(source(id), getToken, { method: "DELETE" });
export const reingestSource = (id: string, getToken: TokenGetter) => apiFetch<AdminJobRef>(`${source(id)}/reingest`, getToken, { method: "POST" });

export const adminJob = (id: string, getToken: TokenGetter) => apiFetch<AdminJob>(`/api/admin/jobs/${encodeURIComponent(id)}`, getToken);
export const generateSubject = (id: string, getToken: TokenGetter) => apiFetch<AdminJobRef>(`${subject(id)}/generate`, getToken, { method: "POST" });
export const publishSubject = (id: string, getToken: TokenGetter) => apiFetch<AdminSubject>(`${subject(id)}/publish`, getToken, { method: "POST" });
export const unpublishSubject = (id: string, getToken: TokenGetter) => apiFetch<AdminSubject>(`${subject(id)}/unpublish`, getToken, { method: "POST" });
