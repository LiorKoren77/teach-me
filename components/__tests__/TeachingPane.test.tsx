import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TeachingPane } from "../TeachingPane";
import { t } from "@/lib/i18n";

describe("TeachingPane", () => {
  it("renders markdown and a thumbnail per figure", () => {
    render(<TeachingPane title="Intro" body={"# Heading\n\nLook at page 12.\n\n- a"} keyPoints={["k1"]}
                         figures={[{ page: 12, label: "7", src: "blob:page-12" }]} strings={t("en")} reexplanation={null} truncated={false} />);
    expect(screen.getByRole("heading", { name: "Teaching" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Intro" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
    expect(screen.getByText("k1")).toBeInTheDocument();
    // The caption is the number printed on the page, not the corpus index the API is asked for.
    expect(screen.getByRole("img", { name: "Page 7" })).toHaveAttribute("src", "blob:page-12");
  });
  it("shows a figure that has not arrived yet as a placeholder", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} figures={[{ page: 3, label: "4", src: null }]} strings={t("en")} reexplanation={null} truncated={false} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("button", { name: "Page 4" })).toBeDisabled();
  });
  it("captions a page that carries no printed number neutrally", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} figures={[{ page: 0, label: "", src: "blob:cover" }]} strings={t("en")} reexplanation={null} truncated={false} />);
    expect(screen.getByRole("img", { name: "Figure" })).toBeInTheDocument();
  });
  it("shows the reexplanation above the teaching text when present", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} figures={[]} strings={t("en")} reexplanation="## Again" truncated={false} />);
    expect(screen.getByRole("heading", { name: "Again" })).toBeInTheDocument();
    expect(screen.queryByText(t("en").truncated)).toBeNull();
  });
  it("says so when the reexplanation was cut off at the model's token ceiling", () => {
    render(<TeachingPane title="Intro" body="body" keyPoints={[]} figures={[]} strings={t("en")} reexplanation="## Again" truncated={true} />);
    expect(screen.getByText(t("en").truncated)).toBeInTheDocument();
  });
});
