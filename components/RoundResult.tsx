import type { RoundResult as RoundResultView } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

export function RoundResult({ result, strings, canContinue = true, onContinue }: {
  result: RoundResultView; strings: Strings; canContinue?: boolean; onContinue: () => void;
}) {
  const stalled = result.status === "stalled";
  const reinforcing = result.status === "reinforcing";
  const action = result.passed ? strings.continue : stalled ? strings.retry : strings.nextRound;
  return (
    <div className={`flex flex-col gap-2 rounded border p-4 ${result.passed ? "border-emerald-300 bg-emerald-50" : "border-stone-300 bg-stone-50"}`}>
      <p className="text-base font-medium">{result.passed ? strings.passed : strings.failed}</p>
      <p className="text-sm text-stone-700">{strings.score(Math.round(result.score * 100))}</p>
      {!result.passed && !stalled ? <p className="text-sm text-stone-700">{strings.roundsLeft(result.rounds_left)}</p> : null}
      {stalled ? <p className="text-sm text-stone-700">{strings.stalled}</p> : null}
      {result.weak_section_titles.length === 0 ? null : (
        <div>
          <h3 className="text-sm font-medium text-stone-900">{strings.weakSections}</h3>
          <ul className="mt-1 list-disc ps-6 text-sm text-stone-700">
            {result.weak_section_titles.map((title) => (
              <li key={title}>{title}</li>
            ))}
          </ul>
        </div>
      )}
      <button
        type="button"
        onClick={onContinue}
        // The next round waits for the re-explanation: reading it is the point of reinforcing.
        disabled={reinforcing && !canContinue}
        className="self-start rounded bg-stone-900 px-4 py-2 text-sm text-stone-50 disabled:opacity-50"
      >
        {action}
      </button>
    </div>
  );
}
