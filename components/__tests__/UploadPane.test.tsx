import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UploadPane } from "../UploadPane";
import { t } from "@/lib/i18n";
import type { AdminSource } from "@/lib/api/types";

const strings = t("en");

const source = (over: Partial<AdminSource> = {}): AdminSource => ({
  id: "s1", filename: "book.pdf", media_type: "application/pdf", status: "extracting",
  page_count: null, detected_language: null, error: null, ...over,
});

const props = {
  sources: [] as AdminSource[],
  acceptedMediaTypes: ["application/pdf", "image/png"],
  published: false,
  busy: false,
  strings,
  onUpload: () => undefined,
  onDelete: () => undefined,
  onReingest: () => undefined,
  confirm: () => true,
};

describe("UploadPane", () => {
  it("offers the accepted media types to the file picker and names them", () => {
    render(<UploadPane {...props} />);

    const input = screen.getByLabelText(strings.chooseFile);
    expect(input).toHaveAttribute("accept", "application/pdf,image/png");
    expect(screen.getByText(strings.acceptedTypes("application/pdf, image/png"))).toBeInTheDocument();
  });

  it("disables the picker and the upload button while the subject is published", () => {
    render(<UploadPane {...props} published sources={[source({ status: "ready", page_count: 2 })]} />);

    expect(screen.getByLabelText(strings.chooseFile)).toBeDisabled();
    expect(screen.getByRole("button", { name: strings.upload })).toBeDisabled();
    expect(screen.getByText(strings.uploadLocked)).toBeInTheDocument();
  });

  it("shows one row per source with its status, page count, language and error", () => {
    render(
      <UploadPane
        {...props}
        sources={[
          source({ id: "a", filename: "one.pdf", status: "ready", page_count: 12, detected_language: "he" }),
          source({ id: "b", filename: "two.pdf", status: "failed", error: "no text layer" }),
        ]}
      />,
    );

    expect(screen.getByText("one.pdf")).toBeInTheDocument();
    expect(screen.getByText(strings.sourceStatus.ready)).toBeInTheDocument();
    expect(screen.getByText(strings.pageCount(12))).toBeInTheDocument();
    expect(screen.getByText(strings.detectedLanguage("he"))).toBeInTheDocument();
    expect(screen.getByText("two.pdf")).toBeInTheDocument();
    expect(screen.getByText(strings.sourceStatus.failed)).toBeInTheDocument();
    expect(screen.getByText("no text layer")).toBeInTheDocument();
  });

  it("uploads the chosen file once, then clears the choice", async () => {
    const onUpload = vi.fn();
    const user = userEvent.setup();
    render(<UploadPane {...props} onUpload={onUpload} />);

    const upload = screen.getByRole("button", { name: strings.upload });
    // Nothing chosen yet, so there is nothing to send.
    expect(upload).toBeDisabled();

    const file = new File(["%PDF-1.4"], "book.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText(strings.chooseFile), file);
    await user.click(upload);

    expect(onUpload).toHaveBeenCalledTimes(1);
    expect(onUpload.mock.calls[0][0].name).toBe("book.pdf");
  });
});
