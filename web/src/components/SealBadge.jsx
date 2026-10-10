// Result of the server-side tamper check (backend/app/seal.py).
// valid = unchanged since signing; altered = edited after signing;
// unsealed = signed before sealing existed (shows nothing).
export default function SealBadge({ status }) {
  if (status === "valid") {
    return <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200" title="Digitally sealed; unchanged since signing">🔒 sealed</span>;
  }
  if (status === "altered") {
    return <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-700 ring-1 ring-red-300" title="This record no longer matches its seal">✖ altered after signing</span>;
  }
  if (status === "unknown_key") {
    return <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-amber-200" title="Sealed with a key this server no longer holds">seal key unknown</span>;
  }
  return null;
}
