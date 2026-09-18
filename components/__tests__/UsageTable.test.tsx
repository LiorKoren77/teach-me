import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UsageTable } from "../UsageTable";
import { t } from "@/lib/i18n";
import type { UsageRow } from "@/lib/api/types";

const rows: UsageRow[] = [
  {
    purpose: "teaching", model: "claude-fake", calls: 3, input_tokens: 1200, output_tokens: 400,
    cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0.0123, avg_latency_ms: 800,
  },
  {
    purpose: "grading", model: "claude-fake", calls: 5, input_tokens: 900, output_tokens: 100,
    cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0.01, avg_latency_ms: 500,
  },
];

describe("UsageTable", () => {
  it("renders one row per usage row with formatted cost and a total row", () => {
    render(<UsageTable rows={rows} strings={t("en")} language="en" />);

    expect(screen.getByText("teaching")).toBeInTheDocument();
    expect(screen.getByText("grading")).toBeInTheDocument();
    expect(screen.getByText("$0.0123")).toBeInTheDocument();
    expect(screen.getByText("$0.0100")).toBeInTheDocument();

    // The total row sums cost across every row and is formatted the same way.
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("$0.0223")).toBeInTheDocument();

    const rowElements = screen.getAllByRole("row");
    // Header row + two data rows + one total row.
    expect(rowElements).toHaveLength(4);
  });

  it("renders a zero total with no rows", () => {
    render(<UsageTable rows={[]} strings={t("en")} language="en" />);
    expect(screen.getByText("$0.0000")).toBeInTheDocument();
  });
});
