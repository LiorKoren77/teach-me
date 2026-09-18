import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { errorKeyOf } from "../api/errors";
import { t } from "../i18n";

describe("errorKeyOf", () => {
  it("maps the statuses the API answers with", () => {
    expect(errorKeyOf(new ApiError(401, "missing or invalid credentials"))).toBe("unauthorized");
    expect(errorKeyOf(new ApiError(403, "not your attempt"))).toBe("forbidden");
    expect(errorKeyOf(new ApiError(404, "no such subject"))).toBe("notFound");
    expect(errorKeyOf(new ApiError(409, "round already answered"))).toBe("conflict");
    expect(errorKeyOf(new ApiError(429, "slow down"))).toBe("rateLimited");
  });
  it("treats any other status, and anything that is not an ApiError, as unknown", () => {
    expect(errorKeyOf(new ApiError(500, "boom"))).toBe("unknown");
    expect(errorKeyOf(new TypeError("offline"))).toBe("unknown");
    expect(errorKeyOf("odd")).toBe("unknown");
  });
  it("every key it can return has a message in every language", () => {
    const keys = ["unauthorized", "forbidden", "notFound", "conflict", "rateLimited", "unknown"] as const;
    for (const code of ["he", "en", "pt"] as const) {
      for (const key of keys) expect(t(code).errors[key]).toBeTruthy();
    }
  });
});
