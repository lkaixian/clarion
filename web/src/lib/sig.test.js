import { describe, expect, it } from "vitest";
import { sigQuantity } from "./sig";

describe("sigQuantity", () => {
  it.each([
    ["1 tab", "TDS x 5/7", 15],
    ["2 tab", "bd x 1/52", 28],
    ["1/2 tab", "OD x 1/12", 15],
    ["1 tab", "nocte x 2 weeks", 14],
    ["1", "q8h x 3 days", 9],
  ])("%s + %s = %i", (dose, sig, qty) => expect(sigQuantity(dose, sig).qty).toBe(qty));

  it("keeps the unit for liquids", () => expect(sigQuantity("5ml", "tds x 5/7")).toEqual({ qty: 75, unit: "ml" }));
  it("rounds partial tablets up", () => expect(sigQuantity("1/2 tab", "od x 5/7").qty).toBe(3));
  it.each([["500mg", "tds x 5/7"], ["1 tab", "prn"], ["1 tab", "tds"], ["", "tds x 5/7"]])(
    "cannot work out %j + %j", (dose, sig) => expect(sigQuantity(dose, sig)).toBeNull());
});
