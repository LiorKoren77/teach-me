import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LanguagePicker } from "../LanguagePicker";

describe("LanguagePicker", () => {
  it("renders only the offered options", () => {
    render(<LanguagePicker value="en" options={["en", "he"]} onChange={() => {}} label="Language" />);
    const select = screen.getByLabelText("Language") as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["he", "en"]);
    expect(screen.queryByText("Português")).not.toBeInTheDocument();
  });

  it("calls onChange with the chosen code", async () => {
    const onChange = vi.fn();
    render(<LanguagePicker value="en" options={["he", "en", "pt"]} onChange={onChange} label="שפה" />);
    await userEvent.selectOptions(screen.getByLabelText("שפה"), "he");
    expect(onChange).toHaveBeenCalledWith("he");
  });
});
