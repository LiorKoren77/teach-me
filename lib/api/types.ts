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
export interface RenderedPart { position: number; title: string; body: string; key_points: string[]; sections: SectionContent[]; glossary: GlossaryEntry[]; }
export interface QuestionView { attempt_question_id: string; question_id: string; position: number; round_no: number; total_in_round: number; kind: QuestionKind; prompt: string; choices: string[] | null; }
export interface RoundResult { round_no: number; score: number; passed: boolean; status: PartStatus; rounds_left: number; weak_section_titles: string[]; }
export interface AnswerResult { accepted: boolean; grade: Grade | null; feedback: string; rejection_reason: string | null; next_question: QuestionView | null; round_result: RoundResult | null; }
export interface PartSession { part: RenderedPart; status: PartStatus; attempt_id: string | null; round_no: number; current_question: QuestionView | null; last_round: RoundResult | null; reexplanation: string | null; }
export interface StudentSource { filename: string; media_type: string; page_count: number | null; }
export interface AdminSubject { id: string; name: string; state: string; languages: Language[]; current_outline_version: number | null; }
export interface AdminSource { id: string; filename: string; media_type: string; status: string; page_count: number | null; detected_language: string | null; error: string | null; }
export interface UsageRow { purpose: string; model: string; calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cache_write_tokens: number; cost_usd: number; avg_latency_ms: number; }
