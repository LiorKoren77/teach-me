// TypeScript mirrors of the backend pydantic models. Keep these in step with
// api/teachme/routes/schemas.py, api/teachme/services/learning_views.py,
// api/teachme/services/progress.py (PartView), api/teachme/services/tutorial.py and
// api/teachme/services/usage.py (UsageSummaryRow). UUIDs arrive as strings.

export type Language = "he" | "en" | "pt";
export type PartStatus = "not_started" | "learning" | "quizzing" | "reinforcing" | "passed" | "stalled";
export type Grade = "correct" | "partial" | "incorrect" | "off_topic" | "junk";
export type QuestionKind = "free_text" | "multiple_choice";

export interface SubjectSummary { id: string; name: string; languages: Language[]; parts_total: number; parts_passed: number; }
export interface PartView { part_id: string; position: number; title: string; status: PartStatus; locked: boolean; best_score: number | null; rounds_used: number; }
export interface SubjectView { subject_id: string; name: string; languages: Language[]; parts: PartView[]; }
export interface SectionContent { section_id: string; language: string; title: string; summary: string; }
export interface GlossaryEntry { slug: string; term: string; source_term: string; definition: string; }
// `page_refs` holds global 0-based page indices - what the page-image route takes - and
// `page_labels` the number each of those pages prints, in the same order ("" for a page that
// prints none).
export interface RenderedPart { outline_version: number; published: boolean; position: number; title: string; body: string; key_points: string[]; sections: SectionContent[]; glossary: GlossaryEntry[]; page_refs: number[]; page_labels: string[]; }
export interface QuestionView { attempt_question_id: string; question_id: string; position: number; round_no: number; total_in_round: number; kind: QuestionKind; prompt: string; choices: string[] | null; }
export interface RoundResult { round_no: number; score: number; passed: boolean; status: PartStatus; rounds_left: number; weak_section_titles: string[]; }
export interface AnswerResult { accepted: boolean; grade: Grade | null; feedback: string; rejection_reason: string | null; next_question: QuestionView | null; round_result: RoundResult | null; }
export interface PartSession { part: RenderedPart; status: PartStatus; attempt_id: string | null; round_no: number; current_question: QuestionView | null; last_round: RoundResult | null; reexplanation: string | null; }
export interface StudentSource { filename: string; media_type: string; page_count: number | null; }
export interface AdminSubject { id: string; name: string; state: string; languages: Language[]; current_outline_version: number | null; }
export interface AdminSource { id: string; filename: string; media_type: string; status: string; page_count: number | null; detected_language: string | null; error: string | null; }
export interface UsageRow { purpose: string; model: string; calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cache_write_tokens: number; cost_usd: number; avg_latency_ms: number; }

// --- Admin upload pane (stage 5) -------------------------------------------------------------
// Mirrors api/teachme/routes/schemas.py's Capabilities, AdminJob and AdminSubjectStatus, and
// api/teachme/services/tutorial.py's status view (the same numbers `teachme tutorial status`
// prints). Every one of these is behind the admin role.

/** The media types `SourceService` accepts, for the file picker's `accept`. */
export interface AdminCapabilities { accepted_media_types: string[]; }
export type JobStatus = "queued" | "running" | "done" | "failed";
export interface AdminJob { id: string; kind: string; status: JobStatus; attempts: number; error: string | null; }
/** What an upload answers with: the registered source, plus the ingestion job now queued for it. */
export interface AdminUpload extends AdminSource { job_id: string; }
export interface AdminJobRef { job_id: string; }
export interface AdminLanguageStatus { language: Language; parts_ready: number; parts_total: number; questions: number; complete: boolean; failed: number[]; }
export interface AdminSubjectStatus {
  state: string;
  outline_version: number | null;
  published_version: number | null;
  parts_total: number;
  languages: AdminLanguageStatus[];
  /** True when some outline version is complete in every enabled language; `publish` takes it. */
  publishable: boolean;
  publishable_version: number | null;
}
