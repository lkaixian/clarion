import { useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getCurrentUser, switchRole, errorMessage } from "../api/client";
import { landingPathFor } from "../lib/access";
import { roleLabel } from "../lib/role";
import { tr } from "../lib/i18n";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";

// Only for accounts that hold more than one role. A native <select>, so it is
// keyboard and screen-reader usable as is. Pages read the user on render, so the
// route change after the switch makes guards and nav follow the new role.
export default function RoleSwitcher() {
  const user = getCurrentUser();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const id = useId();
  const [err, setErr] = useState("");
  const [ask, setAsk] = useState(null); // { role, needsCode } while re-entering the password
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const pwRef = useRef(null);
  const selRef = useRef(null);
  useEffect(() => { if (ask) pwRef.current?.focus(); }, [ask]);
  if (!user?.roles || user.roles.length < 2) return null;

  const cancel = () => { setAsk(null); setPw(""); setCode(""); setErr(""); selRef.current?.focus(); };

  async function go(role, creds) {
    setErr("");
    try {
      await switchRole(role, creds);
      setPw(""); setCode(""); setAsk(null);
      const home = landingPathFor(getCurrentUser());
      if (home === pathname) navigate(0);
      else navigate(home);
    } catch (ex) {
      const d = ex?.response?.data?.detail;
      if (ex?.response?.status === 428 && d?.reauth_required) { setAsk({ role, needsCode: !!d.needs_code }); setPw(""); setCode(""); return; }
      setErr(errorMessage(ex, tr("Could not switch role.")));
    }
  }

  function pick(e) {
    const role = e.target.value;
    setAsk(null);
    if (role !== user.role) go(role);
  }

  function submit(e) {
    e.preventDefault();
    go(ask.role, ask.needsCode ? { password: pw, code } : { password: pw });
  }

  return (
    <div className="px-1">
      <label htmlFor={id} className="block text-[11px] text-blue-300">{tr("Acting as")}</label>
      <select
        ref={selRef}
        id={id}
        value={user.role}
        onChange={pick}
        className={`mt-0.5 w-full rounded-lg bg-blue-800 px-3 py-2 text-sm text-white hover:bg-blue-700 ${FOCUS}`}
      >
        {user.roles.map((r) => <option key={r} value={r}>{tr(roleLabel(r))}</option>)}
      </select>
      {ask && (
        <form onSubmit={submit} onKeyDown={(e) => e.key === "Escape" && cancel()} aria-label={tr("Confirm it is you")} className="mt-1 space-y-1 rounded-lg bg-blue-950 p-2 text-sm text-white">
          <p className="text-xs text-blue-200">{tr("Confirm it is you to switch to this role.")}</p>
          <label className="block text-xs text-blue-200">{tr("Password")}
            <input ref={pwRef} type="password" required autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)}
              className={`mt-0.5 block w-full rounded bg-white px-2 py-1 text-slate-900 ${FOCUS}`} />
          </label>
          {ask.needsCode && (
            <label className="block text-xs text-blue-200">{tr("Authenticator code")}
              <input required inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)}
                className={`mt-0.5 block w-full rounded bg-white px-2 py-1 text-slate-900 ${FOCUS}`} />
            </label>
          )}
          <div className="flex gap-2 pt-1">
            <button type="submit" className={`rounded bg-blue-700 px-3 py-1 hover:bg-blue-600 ${FOCUS}`}>{tr("Switch role")}</button>
            <button type="button" onClick={cancel} className={`rounded border border-blue-400 px-3 py-1 hover:bg-blue-800 ${FOCUS}`}>{tr("Cancel")}</button>
          </div>
        </form>
      )}
      {err && <p role="alert" className="px-1 pt-1 text-xs text-red-300">{err}</p>}
    </div>
  );
}
