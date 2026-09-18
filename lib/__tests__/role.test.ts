import { describe, expect, it } from "vitest";
import { isAdmin } from "../role";

describe("isAdmin", () => {
  it("reads the role claim the backend reads", () => {
    expect(isAdmin({ role: "admin" })).toBe(true);
    expect(isAdmin({ public_metadata: { role: "admin" } })).toBe(true);
  });
  it("treats everything else as a student", () => {
    expect(isAdmin({ role: "student" })).toBe(false);
    expect(isAdmin({ public_metadata: { role: "student" } })).toBe(false);
    expect(isAdmin({})).toBe(false);
    expect(isAdmin(null)).toBe(false);
    expect(isAdmin(undefined)).toBe(false);
  });
});
