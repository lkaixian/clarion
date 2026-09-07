import { useEffect, useRef, useState } from "react";
import Layout from "../components/Layout";
import SignaturePad from "../components/SignaturePad";
import { dataUrlToPngBlob } from "../lib/image";
import {
  getCurrentUser,
  refreshCurrentUser,
  getMySignatureBlob,
  uploadMySignature,
  deleteMySignature,
} from "../api/client";

// Matches the backend limit in routers/profile.py (MAX_SIGNATURE_BYTES).
const MAX_SIGNATURE_BYTES = 500 * 1024;

// Any authenticated staff member's own profile. Route is wrapped in
// <Protected> only (no RequirePage) — a signature isn't a "console page",
// every non-patient role needs one to complete consultations / sign off
// records.
export default function Profile() {
  const [user, setUser] = useState(() => getCurrentUser());
  const [sigUrl, setSigUrl] = useState(null);
  const [replacing, setReplacing] = useState(false);
  const [draft, setDraft] = useState(null); // data-URL from the pad, or null
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sigUrlRef = useRef(null);

  const hasSignature = !!user?.has_signature;

  // (Re)load the saved signature image whenever we believe one exists.
  // Fetched as a blob (auth header required) → object URL; the previous URL
  // is revoked here and the last one on unmount.
  useEffect(() => {
    if (!hasSignature) {
      setSigUrl(null);
      return undefined;
    }
    let cancelled = false;
    getMySignatureBlob()
      .then((url) => {
        if (cancelled) {
          if (url) URL.revokeObjectURL(url);
          return;
        }
        if (sigUrlRef.current) URL.revokeObjectURL(sigUrlRef.current);
        sigUrlRef.current = url;
        setSigUrl(url);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load your saved signature.");
      });
    return () => {
      cancelled = true;
    };
  }, [hasSignature]);

  useEffect(
    () => () => {
      if (sigUrlRef.current) URL.revokeObjectURL(sigUrlRef.current);
    },
    [],
  );

  // Refresh the cached mb_user so has_signature flips app-wide (nav nudge,
  // the sign-off modal's "no signature" branch, etc.) without a re-login.
  async function syncUser() {
    try {
      setUser(await refreshCurrentUser());
    } catch {
      setUser(getCurrentUser());
    }
  }

  async function handleSave() {
    const blob = dataUrlToPngBlob(draft);
    if (!blob) {
      setError("Draw your signature first.");
      return;
    }
    if (blob.size > MAX_SIGNATURE_BYTES) {
      setError("That signature image is too large — draw a simpler one.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await uploadMySignature(blob);
      setDraft(null);
      setReplacing(false);
      await syncUser();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not save your signature. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove() {
    if (!confirm("Remove your saved signature? You'll be asked to draw one next time you sign off a record.")) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await deleteMySignature();
      if (sigUrlRef.current) {
        URL.revokeObjectURL(sigUrlRef.current);
        sigUrlRef.current = null;
      }
      setSigUrl(null);
      setReplacing(false);
      setDraft(null);
      await syncUser();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not remove your signature. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null; // <Protected> handles the redirect to /

  const showPad = !hasSignature || replacing;

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Profile</h1>
        <p className="text-sm text-slate-500">
          Signed in as {user.full_name} · {user.role}
          {user.facility ? ` · ${user.facility}` : ""}
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4 max-w-lg">
        <h2 className="font-semibold text-slate-800 mb-3">Your signature</h2>
        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}

        {hasSignature && !replacing ? (
          <>
            {sigUrl ? (
              <img
                src={sigUrl}
                alt="Your saved signature"
                className="border border-slate-200 rounded-lg bg-white"
                style={{ width: 360, height: 140, objectFit: "contain" }}
              />
            ) : (
              <p className="text-sm text-slate-400">Loading…</p>
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setReplacing(true);
                  setDraft(null);
                  setError("");
                }}
                className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg"
              >
                Replace
              </button>
              <button
                type="button"
                onClick={handleRemove}
                disabled={busy}
                className="text-sm border border-red-700 text-red-700 px-3 py-1.5 rounded-lg disabled:opacity-50"
              >
                Remove signature
              </button>
            </div>
          </>
        ) : null}

        {showPad && (
          <>
            <SignaturePad onChange={setDraft} />
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={handleSave}
                disabled={busy || !draft}
                className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
              >
                {busy ? "Saving…" : "Save signature"}
              </button>
              {hasSignature && (
                <button
                  type="button"
                  onClick={() => {
                    setReplacing(false);
                    setDraft(null);
                    setError("");
                  }}
                  className="text-sm border border-slate-300 px-3 py-1.5 rounded-lg"
                >
                  Cancel
                </button>
              )}
            </div>
          </>
        )}

        <p className="text-xs text-slate-400 mt-4">
          Your signature is stamped on consultations you complete and on records you sign off. It's
          stored only on this system.
        </p>
      </div>
    </Layout>
  );
}
