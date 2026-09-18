import type { PartView } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

const TONE: Record<string, string> = {
  passed: "border-emerald-600 bg-emerald-50 text-emerald-900",
  reinforcing: "border-amber-600 bg-amber-50 text-amber-900",
  stalled: "border-red-600 bg-red-50 text-red-900",
};

export function PartProgress({ parts, current, strings, onSelect }: {
  parts: PartView[]; current: number; strings: Strings; onSelect: (position: number) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-stone-600">{strings.partOf(current + 1, parts.length)}</p>
      <ol className="flex flex-wrap items-stretch gap-2">
        {parts.map((part) => {
          const active = part.position === current;
          return (
            <li key={part.part_id}>
              <button
                type="button"
                disabled={part.locked}
                onClick={() => onSelect(part.position)}
                className={`flex flex-col items-start rounded border px-3 py-2 text-start text-sm ${
                  TONE[part.status] ?? "border-stone-300 bg-white text-stone-800"
                } ${active ? "ring-2 ring-stone-900" : ""} ${part.locked ? "opacity-50" : "hover:border-stone-500"}`}
              >
                <span className="font-medium">{part.title}</span>
                <span className="text-xs">{part.locked ? strings.locked : strings.status[part.status]}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
