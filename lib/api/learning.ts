import { apiFetch, type TokenGetter } from "./client";
import type { AnswerResult, Language, PartSession, QuestionView } from "./types";

export const startPart = (subjectId: string, position: number, language: Language, getToken: TokenGetter) =>
  apiFetch<PartSession>(`/api/subjects/${subjectId}/parts/${position}/start`, getToken, { method: "POST", body: JSON.stringify({ language }) });

export const beginRound = (attemptId: string, getToken: TokenGetter) =>
  apiFetch<QuestionView>(`/api/attempts/${attemptId}/round`, getToken, { method: "POST" });

export const submitAnswer = (
  attemptId: string, attemptQuestionId: string, answer: { answer_text?: string; answer_choice?: number }, getToken: TokenGetter,
) => apiFetch<AnswerResult>(`/api/attempts/${attemptId}/answer`, getToken, {
  method: "POST", body: JSON.stringify({ attempt_question_id: attemptQuestionId, ...answer }),
});

export const reexplainUrl = (attemptId: string) => `/api/attempts/${attemptId}/reexplain`;
