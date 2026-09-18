"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { SubjectActions } from "@/components/SubjectActions";
import { UploadPane } from "@/components/UploadPane";
import { UsageTable } from "@/components/UsageTable";
import { useAdmin } from "@/hooks/useAdmin";
import { useAdminActions } from "@/hooks/useAdminActions";
import { useLanguage } from "@/hooks/useLanguage";
import { directionOf, t } from "@/lib/i18n";

// The whole admin surface: the subjects with their state and outline version, and for the one
// selected, its sources (upload, re-ingest, delete), the generate/publish actions with the same
// summary `teachme tutorial status` prints, and the usage table. Role enforcement is the
// backend's job; a 403 shows a plain refusal instead of the panels below.
export function AdminScreen() {
  const { language } = useLanguage();
  const strings = t(language);
  const { subjects, selectedId, usage, forbidden, error, selectSubject, replaceSubject } = useAdmin();
  const actions = useAdminActions(selectedId, replaceSubject);

  return (
    <div dir={directionOf(language)} className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <Link href="/" className="text-lg font-semibold">
          {strings.appName}
        </Link>
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-medium">{strings.admin}</h1>
          <UserButton />
        </div>
      </header>

      {forbidden ? (
        <p className="text-sm text-stone-700">{strings.adminRoleRequired}</p>
      ) : (
        <>
          {error ? <p className="text-sm text-red-700">{strings.errors[error]}</p> : null}
          {actions.error ? <p className="text-sm text-red-700">{strings.errors[actions.error]}</p> : null}

          <section className="rounded-lg border border-stone-200 bg-white p-4">
            <h2 className="text-sm font-medium text-stone-900">{strings.adminSubjects}</h2>
            <ul className="mt-2 flex flex-col gap-2">
              {(subjects ?? []).map((subject) => (
                <li key={subject.id}>
                  <button
                    type="button"
                    onClick={() => selectSubject(subject.id)}
                    aria-pressed={subject.id === selectedId}
                    className={`flex w-full flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded border px-3 py-2 text-start text-sm ${
                      subject.id === selectedId ? "border-stone-900 bg-stone-50" : "border-stone-200 hover:border-stone-400"
                    }`}
                  >
                    <span className="font-medium">{subject.name}</span>
                    <span className="flex gap-3 text-xs text-stone-600">
                      {/* The API sends the enum value; an unknown one is shown as it came. */}
                      <span>{strings.adminState[subject.state] ?? subject.state}</span>
                      <span>{strings.adminVersion(subject.current_outline_version)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {selectedId ? (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <UploadPane
                sources={actions.sources ?? []}
                acceptedMediaTypes={actions.acceptedMediaTypes}
                published={actions.published}
                busy={actions.busy}
                strings={strings}
                onUpload={actions.upload}
                onDelete={actions.remove}
                onReingest={actions.reingest}
              />

              <SubjectActions
                status={actions.status}
                job={actions.job}
                busy={actions.busy}
                strings={strings}
                onGenerate={actions.generate}
                onPublish={actions.publish}
                onUnpublish={actions.unpublish}
              />

              <section className="rounded-lg border border-stone-200 bg-white p-4 lg:col-span-2">
                <h2 className="text-sm font-medium text-stone-900">{strings.adminUsage}</h2>
                <div className="mt-2 overflow-x-auto">
                  <UsageTable rows={usage ?? []} strings={strings} language={language} />
                </div>
              </section>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
