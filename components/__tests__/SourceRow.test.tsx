import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SourceRow } from "../SourceRow";
import { t } from "@/lib/i18n";
import type { AdminSource } from "@/lib/api/types";

const strings = t("en");
const source: AdminSource = {
  id: "s1", filename: "book.pdf", media_type: "application/pdf", status: "ready",
  page_count: 3, detected_language: "en", error: null,
};

describe("SourceRow", () => {
  it("hides delete and reingest while the subject is published", () => {
    render(<SourceRow source={source} published strings={strings} onDelete={() => undefined} onReingest={() => undefined} confirm={() => true} />);

    expect(screen.queryByRole("button", { name: strings.deleteSource })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: strings.reingestSource })).not.toBeInTheDocument();
    // The source itself is still reported.
    expect(screen.getByText("book.pdf")).toBeInTheDocument();
  });

  it("deletes only once the confirmation is accepted", async () => {
    const onDelete = vi.fn();
    const confirm = vi.fn(() => false);
    const user = userEvent.setup();
    const { rerender } = render(
      <SourceRow source={source} published={false} strings={strings} onDelete={onDelete} onReingest={() => undefined} confirm={confirm} />,
    );

    await user.click(screen.getByRole("button", { name: strings.deleteSource }));
    expect(confirm).toHaveBeenCalledWith(strings.confirmDelete("book.pdf"));
    expect(onDelete).not.toHaveBeenCalled();

    const accept = vi.fn(() => true);
    rerender(
      <SourceRow source={source} published={false} strings={strings} onDelete={onDelete} onReingest={() => undefined} confirm={accept} />,
    );
    await user.click(screen.getByRole("button", { name: strings.deleteSource }));
    expect(onDelete).toHaveBeenCalledWith("s1");
  });

  it("reingests behind the same confirmation", async () => {
    const onReingest = vi.fn();
    const user = userEvent.setup();
    render(
      <SourceRow source={source} published={false} strings={strings} onDelete={() => undefined} onReingest={onReingest} confirm={() => true} />,
    );

    await user.click(screen.getByRole("button", { name: strings.reingestSource }));
    expect(onReingest).toHaveBeenCalledWith("s1");
  });
});
