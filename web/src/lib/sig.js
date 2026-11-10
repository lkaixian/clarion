// Malaysian prescription "sig" -> quantity to dispense. Uses the standard Latin
// shorthand (OD/BD/TDS/QDS, nocte, mane, PRN, "x 5/7" = 5 days, "/52" weeks, "/12" months).
// dose = what one intake is ("2 tab", "5ml", "1/2 tab"); sig = frequency + duration ("TDS x 5/7").
// Returns { qty, unit } or null when it cannot be worked out (PRN, no duration, mg-only strength).
const PER_DAY = [
  [/\b(od|qd|mane|nocte|om|on|hs|daily|once)\b/, 1],
  [/\b(bd|bid|b\.d\.?|twice)\b/, 2],
  [/\b(tds|tid|t\.d\.s\.?|thrice)\b/, 3],
  [/\b(qds|qid|q\.d\.s\.?)\b/, 4],
];
const UNIT = /^(tabs?|tablets?|caps?|capsules?|ml|puffs?|drops?|sachets?|amps?|patch(?:es)?|supp(?:ositor(?:y|ies))?|units?|g)\b/;

function num(s) {
  s = s.replace("½", "0.5").replace(/\s+/g, " ").trim();
  const mixed = s.match(/^(\d+) (\d+)\/(\d+)$/);
  if (mixed) return +mixed[1] + mixed[2] / mixed[3];
  const frac = s.match(/^(\d+)\/(\d+)$/);
  return frac ? frac[1] / frac[2] : parseFloat(s);
}

function perDay(t) {
  if (/\b(prn|sos|stat)\b/.test(t)) return null;
  const q = t.match(/\bq\s*(\d+)\s*h\b|\bevery\s+(\d+)\s*hours?\b/);
  if (q) return 24 / (+q[1] || +q[2]);
  const hit = PER_DAY.find(([re]) => re.test(t));
  return hit ? hit[1] : null;
}

function days(t) {
  let m = t.match(/(\d+)\s*\/\s*(7|52|12)\b/);
  if (m) return +m[1] * { 7: 1, 52: 7, 12: 30 }[m[2]];
  m = t.match(/(\d+)\s*(day|week|month)s?\b/);
  return m ? +m[1] * { day: 1, week: 7, month: 30 }[m[2]] : null;
}

export function sigQuantity(dose, sig) {
  const d = (dose || "").toLowerCase().replace("½", " 0.5 ").trim().match(/^(\d+ \d+\/\d+|\d+\/\d+|\d*\.?\d+)\s*([a-z]*)/);
  const t = (sig || "").toLowerCase();
  const n = perDay(t), nd = days(t);
  if (!d || n == null || nd == null) return null;
  const unit = d[2] ? (UNIT.exec(d[2]) ? d[2] : null) : "";
  if (unit === null) return null; // "500mg" is a strength, not how many to take
  return { qty: Math.ceil(num(d[1]) * n * nd), unit };
}
