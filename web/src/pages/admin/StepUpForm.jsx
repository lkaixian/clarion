import { useState } from "react";
import { tr } from "../../lib/i18n";

// Re-enter your own password + authenticator code before a credential reset.
// `code` may stay empty only if you have not enrolled an authenticator (the
// server decides; it answers 400 otherwise).
export default function StepUpForm({ title, busy, error, onSubmit, onCancel }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");

  function submit(e) {
    e.preventDefault();
    onSubmit({ password, code: code.trim() });
  }

  return (
    <form onSubmit={submit} className="border-t border-slate-200 bg-slate-50 px-3 py-2 space-y-2" autoComplete="off">
      <p className="text-xs text-slate-600">{title}</p>
      <div className="flex flex-wrap gap-2">
        <input
          type="password"
          required
          autoComplete="current-password"
          placeholder={tr("Your password")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="border border-slate-300 rounded-lg px-2 py-1 text-xs"
        />
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder={tr("Authenticator code")}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          maxLength={16}
          className="border border-slate-300 rounded-lg px-2 py-1 text-xs"
        />
        <button
          type="submit"
          disabled={busy || !password}
          className="text-xs bg-blue-800 text-white px-2 py-1 rounded-lg disabled:opacity-50"
        >
          {busy ? "Working…" : "Confirm"}
        </button>
        <button type="button" onClick={onCancel} className="text-xs underline text-slate-600">
          Cancel
        </button>
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
    </form>
  );
}
