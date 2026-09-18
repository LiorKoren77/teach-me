import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FigureThumbnail } from "../FigureThumbnail";

describe("FigureThumbnail", () => {
  it("shows a placeholder of the same size while the image is loading", () => {
    render(<FigureThumbnail src={null} label="Page 12" onOpen={() => {}} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("Page 12")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Page 12/ })).toBeDisabled();
  });

  it("renders the fetched image with fixed dimensions and opens it", async () => {
    const onOpen = vi.fn();
    render(<FigureThumbnail src="blob:page-0" label="Page 12" onOpen={onOpen} />);
    const image = screen.getByRole("img", { name: "Page 12" });
    expect(image).toHaveAttribute("src", "blob:page-0");
    expect(image).toHaveAttribute("width");
    expect(image).toHaveAttribute("height");
    await userEvent.click(screen.getByRole("button", { name: /Page 12/ }));
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
