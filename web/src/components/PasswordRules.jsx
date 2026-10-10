// Password policy checklist. Keep in step with backend
// schemas.password_rule_failures (8+ chars, 1 number, 1 capital, 1 of !@#$*.?).
export const PASSWORD_SPECIALS = "!@#$*.?";

const RULES = [
  ["At least 8 characters", (v) => v.length >= 8],
  ["At least 1 number", (v) => /\d/.test(v)],
  ["At least 1 capital letter", (v) => /[A-Z]/.test(v)],
  [`At least 1 special character (${PASSWORD_SPECIALS.split("").join(" ")})`, (v) => [...v].some((c) => PASSWORD_SPECIALS.includes(c))],
];

export const passwordMeetsRules = (v) => RULES.every(([, ok]) => ok(v));

export default function PasswordRules({ value }) {
  return (
    <ul className="mt-2 space-y-1 text-xs" aria-label="Password requirements">
      {RULES.map(([label, ok]) => {
        const met = ok(value);
        return (
          <li key={label} className={`flex items-center gap-2 ${met ? "text-emerald-700" : "text-slate-500"}`}>
            <span
              aria-hidden="true"
              className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold ${
                met ? "bg-emerald-600 text-white" : "border border-slate-300"
              }`}
            >
              {met ? "✓" : ""}
            </span>
            <span>
              {label}
              <span className="sr-only">{met ? " (met)" : " (not met)"}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
