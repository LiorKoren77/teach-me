import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PartProgress } from "../PartProgress";
import { t } from "@/lib/i18n";

const parts = [
  { part_id: "a", position: 0, title: "A", status: "passed", locked: false, best_score: 80, rounds_used: 1 },
  { part_id: "b", position: 1, title: "B", status: "reinforcing", locked: false, best_score: 20, rounds_used: 1 },
  { part_id: "c", position: 2, title: "C", status: "not_started", locked: true, best_score: null, rounds_used: 0 },
] as const;

describe("PartProgress", () => {
  it("renders one step per part with status labels and locks", () => {
    render(<PartProgress parts={[...parts]} current={1} strings={t("en")} onSelect={() => {}} />);
    expect(screen.getByText("Part 2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /A/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /C/ })).toBeDisabled();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Reviewing")).toBeInTheDocument();
  });
});
