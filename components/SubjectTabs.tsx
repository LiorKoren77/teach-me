import Link from "next/link";
import type { SubjectSummary } from "@/lib/api/types";

export function SubjectTabs({ subjects, activeId }: { subjects: SubjectSummary[]; activeId: string }) {
  if (subjects.length === 0) return null;
  return (
    <nav>
      <ul className="flex flex-wrap items-center gap-2">
        {subjects.map((subject) => {
          const active = subject.id === activeId;
          return (
            <li key={subject.id}>
              <Link
                href={`/learn/${subject.id}`}
                aria-current={active ? "page" : undefined}
                className={`block rounded-t border-b-2 px-3 py-2 text-sm ${
                  active ? "border-stone-900 font-medium text-stone-900" : "border-transparent text-stone-600 hover:text-stone-900"
                }`}
              >
                {subject.name}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
