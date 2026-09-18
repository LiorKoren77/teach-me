import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DialogPane } from "../DialogPane";
import { t } from "@/lib/i18n";
import type { AnswerResult, PartSession, PartStatus, QuestionView, RoundResult } from "@/lib/api/types";

const part = { position: 0, title: "Intro", body: "b", key_points: [], sections: [], glossary: [], page_refs: [], page_labels: [] };

function session(status: PartStatus): PartSession {
  return { part, status, attempt_id: "att", round_no: 1, current_question: null, last_round: null, reexplanation: null };
}

const question: QuestionView = {
  attempt_question_id: "aq", question_id: "q", position: 0, round_no: 1, total_in_round: 2,
  kind: "free_text", prompt: "Why does it rain?", choices: null,
};
const graded: AnswerResult = {
  accepted: true, grade: "partial", feedback: "Close - name the cooling step.",
  rejection_reason: null, next_question: null, round_result: null,
};
const failedRound: RoundResult = {
  round_no: 1, score: 0.4, passed: false, status: "reinforcing", rounds_left: 2, weak_section_titles: ["Evaporation"],
};

const shared = { busy: false, streaming: false, strings: t("en"), onStartRound: () => {}, onSubmit: async () => {}, onContinue: () => {} };

describe("DialogPane", () => {
  it("offers the questions while the student is still reading", () => {
    render(<DialogPane session={session("learning")} question={null} lastAnswer={null} roundResult={null} {...shared} />);
    expect(screen.getByRole("button", { name: "Start the questions" })).toBeEnabled();
  });

  it("renders the open question", () => {
    render(<DialogPane session={session("quizzing")} question={question} lastAnswer={null} roundResult={null} {...shared} />);
    expect(screen.getByText("Why does it rain?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit answer" })).toBeInTheDocument();
  });

  it("shows the feedback for the answer just graded", () => {
    render(<DialogPane session={session("quizzing")} question={question} lastAnswer={graded} roundResult={null} {...shared} />);
    expect(screen.getByText("Partly right")).toBeInTheDocument();
    expect(screen.getByText("Close - name the cooling step.")).toBeInTheDocument();
  });

  it("shows the round result with its score and weak sections", () => {
    render(<DialogPane session={session("reinforcing")} question={null} lastAnswer={graded} roundResult={failedRound} {...shared} />);
    expect(screen.getByText("Not yet")).toBeInTheDocument();
    expect(screen.getByText("Score: 40%")).toBeInTheDocument();
    expect(screen.getByText("2 rounds left")).toBeInTheDocument();
    expect(screen.getByText("We will go over:")).toBeInTheDocument();
    expect(screen.getByText("Evaporation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start the next round" })).toBeEnabled();
  });

  it("waits for the re-explanation before the next round", () => {
    render(<DialogPane session={session("reinforcing")} question={null} lastAnswer={null} roundResult={failedRound} {...shared} streaming={true} />);
    expect(screen.getByRole("button", { name: "Start the next round" })).toBeDisabled();
    expect(screen.getByText("Explaining this differently…")).toBeInTheDocument();
  });

  it("congratulates a passed round and offers the next part", () => {
    const passed: RoundResult = { round_no: 2, score: 0.9, passed: true, status: "passed", rounds_left: 1, weak_section_titles: [] };
    render(<DialogPane session={session("passed")} question={null} lastAnswer={null} roundResult={passed} {...shared} />);
    expect(screen.getByText("Part passed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("offers a fresh start when the part stalled", () => {
    const stalled: RoundResult = { round_no: 3, score: 0.2, passed: false, status: "stalled", rounds_left: 0, weak_section_titles: [] };
    render(<DialogPane session={session("stalled")} question={null} lastAnswer={null} roundResult={stalled} {...shared} />);
    expect(screen.getByText("Let's start this part again")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start again" })).toBeEnabled();
  });

  it("offers a fresh start for a stalled session with no round in hand", () => {
    render(<DialogPane session={session("stalled")} question={null} lastAnswer={null} roundResult={null} {...shared} />);
    expect(screen.getByRole("button", { name: "Start again" })).toBeEnabled();
  });
});
