"use client";
import { useState } from "react";
import type { AnswerResult, QuestionView } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

const MAX_ANSWER = 1500;

// The prompt and the choices are model-written teaching text, but they are rendered as text
// nodes all the same: a question is one line, and Markdown here would only be a second way for
// a prompt to reach the DOM as markup. The answer never leaves this component as HTML either.
export function QuestionCard({ question, busy, strings, onSubmit }: {
  question: QuestionView; busy: boolean; strings: Strings;
  // Resolves with what the API made of the answer, or null when nothing was sent. The card
  // needs the outcome: a rejected answer is one the student has to rewrite, so it stays put.
  onSubmit: (answer: { answer_text?: string; answer_choice?: number }) => Promise<AnswerResult | null>;
}) {
  const [text, setText] = useState("");
  const [choice, setChoice] = useState<number | null>(null);
  const choices = question.kind === "multiple_choice" ? question.choices : null;
  const ready = choices ? choice !== null : text.trim().length > 0;

  // The answer is only thrown away once it has been accepted: a submit that fails, and a
  // rejection the student is asked to rewrite, both leave what they wrote where it is. The
  // failure itself is the caller's to report.
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !ready) return;
    let result: AnswerResult | null;
    try {
      result = await onSubmit(choices ? { answer_choice: choice as number } : { answer_text: text.trim() });
    } catch {
      return;
    }
    if (!result?.accepted) return;
    setText("");
    setChoice(null);
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-3">
      <p className="text-xs text-stone-500">{strings.questionOf(question.position + 1, question.total_in_round)}</p>
      <p className="whitespace-pre-wrap text-base font-medium text-stone-900">{question.prompt}</p>

      {choices ? (
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm text-stone-600">{strings.chooseOne}</legend>
          {choices.map((option, index) => (
            <label key={option} className="flex items-start gap-2 text-sm text-stone-800">
              <input
                type="radio"
                name={`choice-${question.attempt_question_id}`}
                value={index}
                checked={choice === index}
                disabled={busy}
                onChange={() => setChoice(index)}
                className="mt-1"
              />
              <span>{option}</span>
            </label>
          ))}
        </fieldset>
      ) : (
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          disabled={busy}
          maxLength={MAX_ANSWER}
          rows={4}
          aria-label={strings.answerPlaceholder}
          placeholder={strings.answerPlaceholder}
          className="w-full rounded border border-stone-300 p-2 text-sm"
        />
      )}

      <button
        type="submit"
        disabled={busy || !ready}
        className="self-start rounded bg-stone-900 px-4 py-2 text-sm text-stone-50 disabled:opacity-50"
      >
        {strings.submit}
      </button>
    </form>
  );
}
