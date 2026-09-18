import { describe, expect, it } from "vitest";
import { LANGUAGES, directionOf, t } from "../i18n";

/** Every key in the block, sub-maps (status, grade, errors, usage) included, as dotted paths. */
function paths(strings: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(strings)
    .flatMap(([key, value]) =>
      value !== null && typeof value === "object"
        ? paths(value as Record<string, unknown>, `${prefix}${key}.`)
        : [`${prefix}${key}`],
    )
    .sort();
}

describe("i18n", () => {
  it("has the same keys for every language, sub-maps included", () => {
    const keys = paths(t("en"));
    expect(keys).toContain("errors.unauthorized");
    expect(keys).toContain("status.reinforcing");
    for (const { code } of LANGUAGES) expect(paths(t(code))).toEqual(keys);
  });
  it("hebrew is rtl", () => {
    expect(directionOf("he")).toBe("rtl");
    expect(directionOf("pt")).toBe("ltr");
  });
});
