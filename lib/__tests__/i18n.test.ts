import { describe, expect, it } from "vitest";
import type { Strings } from "../i18n";
import { LANGUAGES, directionOf, t } from "../i18n";
import type { Language } from "../api/types";

// Compile-time parity: the table is declared as Record<Language, Strings>, so a key missing from
// he or pt - or one whose shape drifts from en's - fails `next build` rather than this test.
const TABLE = { he: t("he"), en: t("en"), pt: t("pt") } satisfies Record<Language, Strings>;

/** Every key in the block, sub-maps (status, grade, errors, usage) included, as dotted paths. */
function paths(strings: object, prefix = ""): string[] {
  return Object.entries(strings)
    .flatMap(([key, value]) =>
      value !== null && typeof value === "object" ? paths(value as object, `${prefix}${key}.`) : [`${prefix}${key}`],
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
  it("types every language against the same Strings interface", () => {
    expect(Object.keys(TABLE).sort()).toEqual(["en", "he", "pt"]);
  });
  it("hebrew is rtl", () => {
    expect(directionOf("he")).toBe("rtl");
    expect(directionOf("pt")).toBe("ltr");
  });
});
