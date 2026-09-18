"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { LanguagePicker } from "@/components/LanguagePicker";
import { useLanguage } from "@/hooks/useLanguage";
import { useSubjects } from "@/hooks/useSubjects";
import type { Language, SubjectSummary } from "@/lib/api/types";
import { LANGUAGES, t } from "@/lib/i18n";

const EVERY_LANGUAGE: Language[] = LANGUAGES.map((l) => l.code);

export default function Home() {
  const { isLoaded, isSignedIn } = useAuth();
  const { language, chooseLanguage } = useLanguage();
  const strings = t(language);
  const { subjects, error } = useSubjects();

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-8 p-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{strings.appName}</h1>
        {isLoaded && isSignedIn ? (
          <div className="flex items-center gap-4">
            <LanguagePicker value={language} options={EVERY_LANGUAGE} onChange={chooseLanguage} label={strings.language} />
            <Link className="text-sm underline" href="/admin">
              {strings.admin}
            </Link>
            <UserButton />
          </div>
        ) : null}
      </header>

      {!isLoaded ? null : !isSignedIn ? (
        <main className="flex flex-1 flex-col items-start justify-center gap-6">
          <SignInButton mode="modal">
            <button type="button" className="rounded bg-stone-900 px-4 py-2 text-stone-50">
              {strings.signIn}
            </button>
          </SignInButton>
        </main>
      ) : (
        <main className="flex flex-col gap-4">
          <h2 className="text-lg font-medium">{strings.subjects}</h2>
          {error ? <p className="text-sm text-red-700">{strings.errors[error]}</p> : null}
          {subjects === null ? null : subjects.length === 0 ? (
            <p className="text-sm text-stone-600">{strings.noSubjects}</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {subjects.map((subject) => (
                <li key={subject.id}>
                  <SubjectCard subject={subject} partOf={strings.partOf} />
                </li>
              ))}
            </ul>
          )}
        </main>
      )}
    </div>
  );
}

function SubjectCard({ subject, partOf }: { subject: SubjectSummary; partOf: (n: number, total: number) => string }) {
  const done = subject.parts_total === 0 ? 0 : Math.round((subject.parts_passed / subject.parts_total) * 100);
  return (
    <Link
      href={`/learn/${subject.id}`}
      className="block rounded-lg border border-stone-200 bg-white p-4 hover:border-stone-400"
    >
      <span className="flex items-baseline justify-between gap-4">
        <span className="font-medium">{subject.name}</span>
        <span className="text-sm text-stone-600">{partOf(subject.parts_passed, subject.parts_total)}</span>
      </span>
      <span className="mt-3 block h-2 w-full overflow-hidden rounded bg-stone-200">
        <span className="block h-full rounded bg-stone-700" style={{ width: `${done}%` }} />
      </span>
    </Link>
  );
}
