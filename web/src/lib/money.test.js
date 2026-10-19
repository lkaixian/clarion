import { describe, expect, it } from "vitest";
import { rm, toCents } from "./money";

describe("toCents", () => {
  it("accepts whole and 1-2 decimal ringgit", () => {
    expect(toCents("25")).toBe(2500);
    expect(toCents("25.5")).toBe(2550);
    expect(toCents(" 0.05 ")).toBe(5);
    expect(toCents("1234567.89")).toBe(123456789);
  });
  it("rounds away float noise", () => {
    expect(toCents("19.99")).toBe(1999);
    expect(toCents("0.29")).toBe(29);
  });
  it("rejects anything that is not a positive amount", () => {
    for (const bad of ["", "0", "0.00", "-5", "1.234", "abc", "1,000", "5.", ".5", "1e3", "RM 5"]) {
      expect(toCents(bad), bad).toBeNull();
    }
  });
});

describe("rm", () => {
  it("formats cents and tolerates missing values", () => {
    expect(rm(5000)).toBe("RM 50.00");
    expect(rm(5)).toBe("RM 0.05");
    expect(rm(undefined)).toBe("RM 0.00");
  });
});
