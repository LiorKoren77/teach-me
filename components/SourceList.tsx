import type { StudentSource } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

export function SourceList({ sources, strings }: { sources: StudentSource[]; strings: Strings }) {
  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <h2 className="text-sm font-medium text-stone-900">{strings.sources}</h2>
      <ul className="mt-2 flex flex-col gap-2">
        {sources.map((source) => (
          <li key={source.filename} className="text-sm text-stone-700">
            <span className="block break-words">{source.filename}</span>
            {source.page_count === null ? null : (
              <span className="block text-xs text-stone-500">{strings.pageCount(source.page_count)}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
