import { describe, expect, it } from "vitest";
import { extractPageRefs, pageRefsOf } from "../pageRefs";

describe("extractPageRefs", () => {
  it("finds English page references", () => {
    expect(extractPageRefs("See page 4 and Page 12 again, and page 4.")).toEqual([4, 12]);
  });
  it("finds Hebrew page references", () => {
    expect(extractPageRefs("ראו עמוד 7 ואת עמוד 3.")).toEqual([7, 3]);
  });
  it("finds Portuguese page references", () => {
    expect(extractPageRefs("Veja a página 9 e a pagina 2.")).toEqual([9, 2]);
  });
  it("ignores text with no references", () => {
    expect(extractPageRefs("nothing here")).toEqual([]);
  });
});

describe("pageRefsOf", () => {
  const part = { body: "Look at page 4 and page 12." };

  it("uses the page references the backend served", () => {
    expect(pageRefsOf({ ...part, page_refs: [7, 8] })).toEqual([7, 8]);
  });
  it("serves no thumbnails for a part the backend says has no pages", () => {
    expect(pageRefsOf({ ...part, page_refs: [] })).toEqual([]);
  });
  it("falls back to the prose scan while the backend does not send them", () => {
    expect(pageRefsOf(part)).toEqual([4, 12]);
    expect(pageRefsOf({ ...part, page_refs: undefined })).toEqual([4, 12]);
  });
  it("has nothing to show without a part", () => {
    expect(pageRefsOf(null)).toEqual([]);
  });
});
