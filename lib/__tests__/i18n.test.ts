import { describe, expect, it } from "vitest";
import { LANGUAGES, directionOf, t } from "../i18n";

describe("i18n", () => {
  it("has the same keys for every language", () => {
    const keys = Object.keys(t("en")).sort();
    for (const { code } of LANGUAGES) expect(Object.keys(t(code)).sort()).toEqual(keys);
  });
  it("hebrew is rtl", () => {
    expect(directionOf("he")).toBe("rtl");
    expect(directionOf("pt")).toBe("ltr");
  });
});
