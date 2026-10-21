import { describe, expect, it } from "vitest";
import { afterLoginPath, parseEmergencyQr } from "./emergencyQr";

describe("parseEmergencyQr", () => {
  it("keeps the legacy prefix working", () => {
    expect(parseEmergencyQr("CLARION-EMERGENCY:abc123")).toBe("abc123");
  });
  it("reads /e/<ref> from any host and scheme", () => {
    expect(parseEmergencyQr("https://clarion.example/e/abc123")).toBe("abc123");
    expect(parseEmergencyQr(" http://10.0.0.5:8080/e/abc123/?x=1 ")).toBe("abc123");
  });
  it("ignores /e/n/ links and other text", () => {
    expect(parseEmergencyQr("https://h/e/n/04AABB")).toBeNull();
    expect(parseEmergencyQr("https://h/patients/1")).toBeNull();
    expect(parseEmergencyQr("plain-ref")).toBeNull();
    expect(parseEmergencyQr("")).toBeNull();
  });
  it("returns null (does not throw) on malformed percent-encoding", () => {
    expect(parseEmergencyQr("https://h/e/%")).toBeNull();
    expect(parseEmergencyQr("https://h/e/%E0%A4%A")).toBeNull();
  });
  it("decodes a valid percent-encoded ref", () => {
    expect(parseEmergencyQr("https://h/e/a%2Db")).toBe("a-b");
  });
});

describe("afterLoginPath (Login ?next=)", () => {
  const home = () => "/home";
  const next = (v) => afterLoginPath({}, "?next=" + encodeURIComponent(v), home);
  it("accepts a single /e/<ref> path", () => {
    expect(next("/e/abc")).toBe("/e/abc");
    expect(next("/e/abc-1_x")).toBe("/e/abc-1_x");
  });
  it("rejects anything else", () => {
    for (const bad of ["//evil.com", "/e/../x", "https://evil.com", "/e/a/b/c", "/e/a/b", "/e/n/04AA", "/e/abc\n", "/patients/1"]) {
      expect(next(bad)).toBe("/home");
    }
  });
  it("a forced password change wins over next", () => {
    expect(afterLoginPath({ must_change_password: true }, "?next=%2Fe%2Fabc", home)).toBe("/change-password");
  });
  it("falls back to the landing page without next", () => {
    expect(afterLoginPath({}, "", home)).toBe("/home");
  });
});
