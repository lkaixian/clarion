import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getNotifications, markNotificationRead, markAllNotificationsRead } from "../api/client";
import { formatDateTime } from "../lib/format";
import Layout from "../components/Layout";
import { tr } from "../lib/i18n";

// Own notifications, newest first. Opening one marks it read and goes to its
// link. Layout's badge polls the unread count, so it catches up on its own.
export default function Inbox() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const load = () =>
    getNotifications().then(setItems).catch(() => setError("Could not load your inbox."));
  useEffect(() => { load(); }, []);

  async function open(n) {
    try {
      if (!n.read_at) await markNotificationRead(n.id);
    } catch { /* still navigate */ }
    if (n.link) navigate(n.link);
    else load();
  }

  async function readAll() {
    try {
      await markAllNotificationsRead();
      await load();
    } catch {
      setError("Could not mark them read.");
    }
  }

  const unread = (items || []).filter((n) => !n.read_at).length;

  return (
    <Layout>
      <div className="mx-auto max-w-3xl p-4 md:p-8">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-900">{tr("Inbox")}</h1>
          {unread > 0 && (
            <button onClick={readAll} className="text-sm text-blue-700 hover:underline">{tr("Mark all read")}</button>
          )}
        </div>
        {error && <p className="mb-3 text-sm text-red-700">{error}</p>}
        {items === null ? (
          <p className="text-sm text-slate-400">{tr("Loading…")}</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing yet. You&apos;ll be notified here when a result you ordered is signed off.</p>
        ) : (
          <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
            {items.map((n) => (
              <li key={n.id}>
                <button
                  onClick={() => open(n)}
                  className={`flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50 ${n.read_at ? "" : "bg-blue-50/60"}`}
                >
                  <span
                    aria-hidden="true"
                    className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${n.urgent ? "bg-red-600" : n.read_at ? "bg-slate-300" : "bg-blue-600"}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className={`block text-sm ${n.read_at ? "text-slate-700" : "font-semibold text-slate-900"}`}>
                      {n.title}
                      {n.urgent && <span className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-red-800">{tr("Critical")}</span>}
                    </span>
                    {n.body && <span className="block truncate text-sm text-slate-500">{n.body}</span>}
                    <span className="block text-xs text-slate-400">{formatDateTime(n.created_at)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Layout>
  );
}
