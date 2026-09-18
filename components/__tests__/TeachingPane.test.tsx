import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TeachingPane } from "../TeachingPane";
import { t } from "@/lib/i18n";

describe("TeachingPane", () => {
  it("renders markdown and turns page references into thumbnails", () => {
    render(<TeachingPane title="Intro" body={"# Heading\n\nLook at page 12.\n\n- a"} keyPoints={["k1"]} pageRefs={[12]}
                         subjectId="s1" strings={t("en")} reexplanation={null} />);
    expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
    expect(screen.getByText("k1")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Page 12" })).toHaveAttribute("src", "/api/subjects/s1/pages/12/image");
  });
  it("shows the reexplanation above the teaching text when present", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} pageRefs={[]} subjectId="s1" strings={t("en")} reexplanation="## Again" />);
    expect(screen.getByRole("heading", { name: "Again" })).toBeInTheDocument();
  });
});
