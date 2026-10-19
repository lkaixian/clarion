// Money helpers shared by the patient (MyBills) and cashier pages. Amounts are integer cents.
export const rm = (cents) => `RM ${((cents || 0) / 100).toFixed(2)}`;

// "25", "25.5", "25.50" -> cents; anything else (empty, 0, 3 decimals, negative, text) -> null.
export function toCents(text) {
  const t = String(text).trim();
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null;
  const cents = Math.round(parseFloat(t) * 100);
  return cents > 0 ? cents : null;
}