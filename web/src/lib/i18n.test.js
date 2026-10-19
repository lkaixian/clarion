import { describe, expect, it } from "vitest";
import { LANGUAGES, setLang, translate } from "./i18n";

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
});
