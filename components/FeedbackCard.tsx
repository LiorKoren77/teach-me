import type { AnswerResult } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

const TONE: Record<string, string> = {
  correct: "border-emerald-300 bg-emerald-50 text-emerald-900",
  partial: "border-amber-300 bg-amber-50 text-amber-900",
  incorrect: "border-red-300 bg-red-50 text-red-900",
};

// A rejection (off topic, junk, a relevance refusal) shows the backend's own fixed message and
// nothing else: no grade, no colour to read into. Every feedback string is plain text.
export function FeedbackCard({ result, strings }: { result: AnswerResult; strings: Strings }) {
  const tone = result.accepted && result.grade ? TONE[result.grade] ?? "border-stone-300 bg-stone-50 text-stone-800" : "border-stone-300 bg-stone-100 text-stone-700";
  return (
    <div className={`rounded border p-3 ${tone}`}>
      {result.accepted && result.grade ? (
        <p className="text-sm font-medium">{strings.grade[result.grade]}</p>
      ) : null}
      <p className="whitespace-pre-wrap text-sm">{result.feedback}</p>
    </div>
  );
}
