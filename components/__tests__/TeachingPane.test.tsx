import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TeachingPane } from "../TeachingPane";
import { t } from "@/lib/i18n";

describe("TeachingPane", () => {
  it("renders markdown and a thumbnail per figure", () => {
    render(<TeachingPane title="Intro" body={"# Heading\n\nLook at page 12.\n\n- a"} keyPoints={["k1"]}
                         figures={[{ page: 12, src: "blob:page-12" }]} strings={t("en")} reexplanation={null} />);
    expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
    expect(screen.getByText("k1")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Page 12" })).toHaveAttribute("src", "blob:page-12");
  });
  it("shows a figure that has not arrived yet as a placeholder", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} figures={[{ page: 3, src: null }]} strings={t("en")} reexplanation={null} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("button", { name: "Page 3" })).toBeDisabled();
  });
  it("shows the reexplanation above the teaching text when present", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} figures={[]} strings={t("en")} reexplanation="## Again" />);
    expect(screen.getByRole("heading", { name: "Again" })).toBeInTheDocument();
  });
});
