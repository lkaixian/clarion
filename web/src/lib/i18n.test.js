import { describe, expect, it } from "vitest";
import { LANGUAGES, setLang, translate } from "./i18n";
import ms from "./lang/ms.json";
import zh from "./lang/zh.json";
import ta from "./lang/ta.json";

describe("i18n", () => {
  it("falls back to the English text for a missing entry or language", () => {
    expect(translate("Some string nobody translated", "ms")).toBe("Some string nobody translated");
    expect(translate("Sign in", "en")).toBe("Sign in");
  });

  it("translates the sign-in and nav strings into every other language", () => {
    for (const [code] of LANGUAGES.filter(([c]) => c !== "en")) {
      for (const text of ["Sign in", "Patients", "Sign out", "Password"]) {
        expect(translate(text, code)).not.toBe(text);
      }
    }
  });

  it("ignores an unknown language code", () => {
    setLang("xx");
    expect(document.documentElement.lang).not.toBe("xx");
  });

  it("has the same strings in every generated language file", () => {
    const keys = Object.keys(ms).sort();
    expect(Object.keys(zh).sort()).toEqual(keys);
    expect(Object.keys(ta).sort()).toEqual(keys);
    expect(keys.length).toBeGreaterThan(500);
  });
});
