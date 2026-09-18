import { describe, expect, it } from "vitest";
import { extractPageRefs } from "../pageRefs";

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
