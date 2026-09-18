import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QuestionCard } from "../QuestionCard";
import { t } from "@/lib/i18n";

const base = { attempt_question_id: "aq", question_id: "q", position: 1, round_no: 1, total_in_round: 5 };

describe("QuestionCard", () => {
  it("free text: submits trimmed text and disables while busy", async () => {
    const onSubmit = vi.fn();
    render(<QuestionCard question={{ ...base, kind: "free_text", prompt: "Why?", choices: null }} busy={false} strings={t("en")} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByRole("textbox"), "  because  ");
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(onSubmit).toHaveBeenCalledWith({ answer_text: "because" });
  });
  it("multiple choice: submits the chosen index and renders prompt as plain text", async () => {
    const onSubmit = vi.fn();
    render(<QuestionCard question={{ ...base, kind: "multiple_choice", prompt: "<b>Pick</b>", choices: ["a", "b"] }} busy={false} strings={t("en")} onSubmit={onSubmit} />);
    expect(screen.getByText("<b>Pick</b>")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "b" }));
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(onSubmit).toHaveBeenCalledWith({ answer_choice: 1 });
  });
  it("submitting is refused while busy or with an empty answer", () => {
    render(<QuestionCard question={{ ...base, kind: "free_text", prompt: "Why?", choices: null }} busy={true} strings={t("en")} onSubmit={() => {}} />);
    expect(screen.getByRole("button", { name: "Submit answer" })).toBeDisabled();
    expect(screen.getByText("Question 2 of 5")).toBeInTheDocument();
  });
});
