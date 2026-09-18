import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SubjectActions } from "../SubjectActions";
import { t } from "@/lib/i18n";
import type { AdminSubjectStatus } from "@/lib/api/types";

const strings = t("en");
const status = (over: Partial<AdminSubjectStatus> = {}): AdminSubjectStatus => ({
  state: "draft", outline_version: 2, published_version: null, parts_total: 4,
  languages: [{ language: "en", parts_ready: 4, parts_total: 4, questions: 24, complete: true, failed: [] }],
  publishable: true, publishable_version: 2, ...over,
});

const props = {
  job: null,
  jobStale: false,
  busy: false,
  strings,
  onGenerate: () => undefined,
  onPublish: () => undefined,
  onUnpublish: () => undefined,
};

describe("SubjectActions", () => {
  it("summarises the tutorial status and offers publish when the backend says it may", () => {
    render(<SubjectActions {...props} status={status()} />);

    expect(screen.getByText(strings.partsReady(4, 4))).toBeInTheDocument();
    expect(screen.getByText(strings.questionsReady(24))).toBeInTheDocument();
    expect(screen.getByText(strings.publishable(2))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: strings.publish })).toBeEnabled();
    expect(screen.getByRole("button", { name: strings.unpublish })).toBeDisabled();
  });

  it("refuses publish while no version is complete in every language", () => {
    render(
      <SubjectActions
        {...props}
        status={status({
          publishable: false, publishable_version: null,
          languages: [{ language: "he", parts_ready: 1, parts_total: 4, questions: 6, complete: false, failed: [2] }],
        })}
      />,
    );

    expect(screen.getByRole("button", { name: strings.publish })).toBeDisabled();
    expect(screen.getByText(strings.notPublishable)).toBeInTheDocument();
    expect(screen.getByText(strings.failedParts("2"))).toBeInTheDocument();
  });

  it("locks generate and publish once published, and reports the running job", () => {
    render(
      <SubjectActions
        {...props}
        status={status({ state: "published", published_version: 2 })}
        job={{ id: "j1", kind: "generate_subject", status: "running", attempts: 1, error: null }}
      />,
    );

    expect(screen.getByRole("button", { name: strings.generate })).toBeDisabled();
    expect(screen.getByRole("button", { name: strings.publish })).toBeDisabled();
    expect(screen.getByRole("button", { name: strings.unpublish })).toBeEnabled();
    expect(screen.getByText(strings.jobLine(strings.jobKind.generate_subject, strings.jobStatus.running))).toBeInTheDocument();
    expect(screen.getByText(strings.publishedVersion(2))).toBeInTheDocument();
  });

  it("shows the stale note next to the job state once polling gave up on it", () => {
    render(
      <SubjectActions
        {...props}
        status={status({ state: "published", published_version: 2 })}
        job={{ id: "j1", kind: "generate_subject", status: "running", attempts: 1, error: null }}
        jobStale
      />,
    );

    expect(screen.getByText(strings.jobLine(strings.jobKind.generate_subject, strings.jobStatus.running))).toBeInTheDocument();
    expect(screen.getByText(strings.jobStale)).toBeInTheDocument();
  });
});
