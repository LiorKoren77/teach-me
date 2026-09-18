import { FeedbackCard } from "./FeedbackCard";
import { QuestionCard } from "./QuestionCard";
import { RoundResult } from "./RoundResult";
import type { AnswerResult, PartSession, QuestionView, RoundResult as RoundResultView } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

// Which of the five states the dialog is in is decided here, from props alone: the hook that
// owns the flow does the fetching.
export function DialogPane({ session, question, lastAnswer, roundResult, busy, streaming, strings, onStartRound, onSubmit, onContinue }: {
  session: PartSession; question: QuestionView | null; lastAnswer: AnswerResult | null;
  roundResult: RoundResultView | null; busy: boolean; streaming: boolean; strings: Strings;
  onStartRound: () => void; onSubmit: (answer: { answer_text?: string; answer_choice?: number }) => void;
  onContinue: () => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-stone-200 bg-white p-5">
      <h2 className="text-sm font-medium text-stone-500">{strings.dialog}</h2>

      {lastAnswer ? <FeedbackCard result={lastAnswer} strings={strings} /> : null}

      {roundResult ? (
        <RoundResult result={roundResult} strings={strings} canContinue={!streaming} onContinue={onContinue} />
      ) : question ? (
        // Keyed by the question, so the answer box empties itself when the next one arrives.
        <QuestionCard key={question.attempt_question_id} question={question} busy={busy} strings={strings} onSubmit={onSubmit} />
      ) : session.status === "passed" ? (
        <p className="text-sm text-stone-700">{strings.passed}</p>
      ) : session.status === "stalled" ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-stone-700">{strings.stalled}</p>
          <button type="button" onClick={onContinue} disabled={busy} className="self-start rounded bg-stone-900 px-4 py-2 text-sm text-stone-50 disabled:opacity-50">
            {strings.retry}
          </button>
        </div>
      ) : (
        <button type="button" onClick={onStartRound} disabled={busy || !session.attempt_id} className="self-start rounded bg-stone-900 px-4 py-2 text-sm text-stone-50 disabled:opacity-50">
          {strings.startRound}
        </button>
      )}

      {streaming ? <p className="text-sm text-amber-800">{strings.reexplaining}</p> : null}
    </section>
  );
}
