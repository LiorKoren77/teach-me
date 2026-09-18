"use client";
import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { beginRound, startPart, submitAnswer } from "@/lib/api/learning";
import { openSubject } from "@/lib/api/subjects";
import type { AnswerResult, Language, PartSession, QuestionView, RoundResult, SubjectView } from "@/lib/api/types";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** The part to land on: the first one still to pass, else the last one the student can reach. */
function landingPosition(view: SubjectView): number {
  const next = view.parts.find((part) => !part.locked && part.status !== "passed");
  const reachable = view.parts.filter((part) => !part.locked);
  return (next ?? reachable[reachable.length - 1] ?? view.parts[0])?.position ?? 0;
}

/** The language the part is taught in: the reader's choice when the subject teaches it. */
function languageFor(view: SubjectView, preferred: Language): Language {
  return view.languages.includes(preferred) ? preferred : view.languages[0] ?? preferred;
}

/**
 * The whole learning flow for one subject: the subject view (so the progress strip stays true),
 * the open part's session, its current question, the last answer and the last round result.
 *
 * All state is the backend's; every action posts and stores what comes back, and a round result
 * also refetches the subject view, because passing a part unlocks the next one.
 */
export function useLearningSession(subjectId: string, preferred: Language) {
  const { getToken, isSignedIn } = useAuth();
  const [subject, setSubject] = useState<SubjectView | null>(null);
  const [session, setSession] = useState<PartSession | null>(null);
  const [question, setQuestion] = useState<QuestionView | null>(null);
  const [lastAnswer, setLastAnswer] = useState<AnswerResult | null>(null);
  const [roundResult, setRoundResult] = useState<RoundResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPart = useCallback(
    async (view: SubjectView, position: number) => {
      const opened = await startPart(subjectId, position, languageFor(view, preferred), getToken);
      setSession(opened);
      setQuestion(opened.current_question);
      setLastAnswer(null);
      // A resumed part that is waiting on the student (reinforcing, or stalled) shows the round
      // it just finished; one that is being read shows no result at all.
      setRoundResult(opened.status === "reinforcing" || opened.status === "stalled" ? opened.last_round : null);
    },
    [subjectId, preferred, getToken],
  );

  const openRound = useCallback(
    async (attemptId: string) => {
      const next = await beginRound(attemptId, getToken);
      setQuestion(next);
      setLastAnswer(null);
      setRoundResult(null);
      setSession((previous) => (previous ? { ...previous, status: "quizzing", round_no: next.round_no, current_question: next } : previous));
    },
    [getToken],
  );

  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }, []);

  // First load: the subject view, then the part the student is up to. Nothing is set before the
  // first await, so this never writes state during the effect itself.
  useEffect(() => {
    if (!isSignedIn) return;
    let cancelled = false;
    void (async () => {
      try {
        const view = await openSubject(subjectId, getToken);
        if (cancelled) return;
        setSubject(view);
        await loadPart(view, landingPosition(view));
      } catch (failure) {
        if (!cancelled) setError(messageOf(failure));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, subjectId, getToken, loadPart]);

  const open = useCallback(
    (position: number) =>
      run(async () => {
        const view = await openSubject(subjectId, getToken);
        setSubject(view);
        await loadPart(view, position);
      }),
    [run, subjectId, getToken, loadPart],
  );

  const startRound = useCallback(
    () =>
      run(async () => {
        if (session?.attempt_id) await openRound(session.attempt_id);
      }),
    [run, session, openRound],
  );

  const submit = useCallback(
    (answer: { answer_text?: string; answer_choice?: number }) =>
      run(async () => {
        const attemptId = session?.attempt_id;
        if (!attemptId || !question) return;
        const result = await submitAnswer(attemptId, question.attempt_question_id, answer, getToken);
        setLastAnswer(result);
        if (result.round_result) {
          const finished = result.round_result;
          setRoundResult(finished);
          setQuestion(null);
          setSession((previous) => (previous ? { ...previous, status: finished.status, last_round: finished } : previous));
          setSubject(await openSubject(subjectId, getToken));
        } else {
          // A rejection hands back the same question, so the box simply reopens.
          setQuestion(result.next_question);
        }
      }),
    [run, session?.attempt_id, question, subjectId, getToken],
  );

  const continueAfterRound = useCallback(
    () =>
      run(async () => {
        const attemptId = session?.attempt_id;
        const here = session?.part.position ?? 0;
        const status = roundResult?.status ?? session?.status;
        if (status === "reinforcing" && attemptId) {
          await openRound(attemptId);
          return;
        }
        const view = await openSubject(subjectId, getToken);
        setSubject(view);
        if (status === "stalled") {
          // Opening a stalled part starts a fresh attempt, and its bank is asked again.
          await loadPart(view, here);
          return;
        }
        const next = view.parts.find((part) => part.position > here && !part.locked && part.status !== "passed");
        if (next) await loadPart(view, next.position);
        else setRoundResult(null); // Nothing left to unlock; the part stays open to reread.
      }),
    [run, session, roundResult?.status, subjectId, getToken, loadPart, openRound],
  );

  return {
    subject,
    session,
    question,
    lastAnswer,
    roundResult,
    busy,
    error,
    language: subject ? languageFor(subject, preferred) : preferred,
    open,
    startRound,
    submit,
    continueAfterRound,
  };
}
