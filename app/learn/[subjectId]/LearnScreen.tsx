"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useMemo } from "react";
import { DialogPane } from "@/components/DialogPane";
import { LanguagePicker } from "@/components/LanguagePicker";
import { PartProgress } from "@/components/PartProgress";
import { SourceList } from "@/components/SourceList";
import { SubjectTabs } from "@/components/SubjectTabs";
import { TeachingPane } from "@/components/TeachingPane";
import { useLanguage } from "@/hooks/useLanguage";
import { useLearningSession } from "@/hooks/useLearningSession";
import { usePageImages } from "@/hooks/usePageImage";
import { useReexplainStream } from "@/hooks/useReexplainStream";
import { useSources, useSubjects } from "@/hooks/useSubjects";
import { directionOf, t } from "@/lib/i18n";
import { extractPageRefs } from "@/lib/pageRefs";

// The screen from the spec: subject tabs and the part strip on top, the teaching text above the
// tutor dialog in the main column, the sources on the right, stacked on narrow screens. It holds
// no state of its own - the hooks own the flow and the components take plain props.
export function LearnScreen({ subjectId }: { subjectId: string }) {
  const { language: preferred, chooseLanguage } = useLanguage();
  const { subjects } = useSubjects();
  const { sources } = useSources(subjectId);
  const { subject, session, question, lastAnswer, roundResult, busy, error, language, open, startRound, submit, continueAfterRound } =
    useLearningSession(subjectId, preferred);

  const strings = t(language);
  const attemptId = session?.attempt_id ?? null;
  const reinforcing = roundResult?.status === "reinforcing";
  const stream = useReexplainStream(attemptId, roundResult?.round_no ?? null, reinforcing && attemptId !== null);
  const body = session?.part.body ?? "";
  const pageRefs = useMemo(() => extractPageRefs(body), [body]);
  const pageUrls = usePageImages(subjectId, pageRefs);
  const figures = useMemo(() => pageRefs.map((page) => ({ page, src: pageUrls[page] ?? null })), [pageRefs, pageUrls]);

  return (
    <div dir={directionOf(language)} className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link href="/" className="text-lg font-semibold">
            {strings.appName}
          </Link>
          <div className="flex items-center gap-4">
            <LanguagePicker
              value={language}
              options={subject?.languages ?? [language]}
              onChange={chooseLanguage}
              label={strings.language}
            />
            <UserButton />
          </div>
        </div>
        <SubjectTabs subjects={subjects ?? []} activeId={subjectId} />
        {subject && session ? (
          <PartProgress parts={subject.parts} current={session.part.position} strings={strings} onSelect={open} />
        ) : null}
      </header>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}
      {stream.error ? <p className="text-sm text-red-700">{stream.error}</p> : null}

      {session ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_280px]">
          <main className="flex flex-col gap-6">
            <TeachingPane
              title={session.part.title}
              body={session.part.body}
              keyPoints={session.part.key_points}
              figures={figures}
              strings={strings}
              // The stream's own text while it runs, the stored one when a reinforcing part is
              // resumed in a later visit.
              reexplanation={stream.text || session.reexplanation || null}
            />
            <DialogPane
              session={session}
              question={question}
              lastAnswer={lastAnswer}
              roundResult={roundResult}
              busy={busy}
              streaming={stream.streaming}
              strings={strings}
              onStartRound={startRound}
              onSubmit={submit}
              onContinue={continueAfterRound}
            />
          </main>
          <aside>
            <SourceList sources={sources ?? []} strings={strings} />
          </aside>
        </div>
      ) : null}
    </div>
  );
}
