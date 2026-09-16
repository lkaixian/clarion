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
  updateMyProfile,
  getMyPhotoBlob,
  uploadMyPhoto,
  deleteMyPhoto,
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

  // Bio / internal contact email / photo. `bio` is PUBLIC (shown on a
  // patient's self-booking clinician picker); `contact_email` is
  // internal-only, separate from the real login email above.
  const [bio, setBio] = useState(user?.bio || "");
  const [contactEmail, setContactEmail] = useState(user?.contact_email || "");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileMsg, setProfileMsg] = useState("");
  const [photoUrl, setPhotoUrl] = useState(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const photoUrlRef = useRef(null);

  const hasSignature = !!user?.has_signature;
  const hasPhoto = !!user?.has_photo;

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

  useEffect(() => {
    if (!hasPhoto) {
      setPhotoUrl(null);
      return undefined;
    }
    let cancelled = false;
    getMyPhotoBlob()
      .then((url) => {
        if (cancelled) {
          if (url) URL.revokeObjectURL(url);
          return;
        }
        if (photoUrlRef.current) URL.revokeObjectURL(photoUrlRef.current);
        photoUrlRef.current = url;
        setPhotoUrl(url);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load your saved photo.");
      });
    return () => {
      cancelled = true;
    };
  }, [hasPhoto]);

  useEffect(
    () => () => {
      if (photoUrlRef.current) URL.revokeObjectURL(photoUrlRef.current);
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

  async function saveProfile() {
    setProfileBusy(true);
    setProfileMsg("");
    try {
      await updateMyProfile({ bio: bio || null, contact_email: contactEmail || null });
      await syncUser();
      setProfileMsg("Saved");
    } catch (err) {
      setProfileMsg(err?.response?.data?.detail || "Could not save. Try again.");
    } finally {
      setProfileBusy(false);
    }
  }

  async function changePhoto(file) {
    if (!file) return;
    setPhotoBusy(true);
    setError("");
    try {
      await uploadMyPhoto(file);
      await syncUser();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not upload that photo. Try again.");
    } finally {
      setPhotoBusy(false);
    }
  }

  async function removePhoto() {
    if (!confirm("Remove your profile photo?")) return;
    setPhotoBusy(true);
    setError("");
    try {
      await deleteMyPhoto();
      await syncUser();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not remove your photo. Try again.");
    } finally {
      setPhotoBusy(false);
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
        <h2 className="font-semibold text-slate-800 mb-3">Your profile</h2>

        <div className="flex items-start gap-4 mb-4">
          <div className="shrink-0">
            {photoUrl ? (
              <img
                src={photoUrl}
                alt="Your profile photo"
                className="w-20 h-20 rounded-full object-cover border border-slate-200 bg-white"
              />
            ) : (
              <div className="w-20 h-20 rounded-full border border-slate-200 bg-slate-50" />
            )}
            <div className="mt-1 flex flex-col items-center gap-1">
              <label className="text-xs text-blue-800 cursor-pointer">
                {photoBusy ? "Working…" : hasPhoto ? "Replace" : "Upload"}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/heic"
                  className="hidden"
                  disabled={photoBusy}
                  onChange={(e) => changePhoto(e.target.files?.[0])}
                />
              </label>
              {hasPhoto && (
                <button
                  type="button"
                  onClick={removePhoto}
                  disabled={photoBusy}
                  className="text-xs text-red-700 disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <label className="block text-xs font-medium text-slate-500 mb-1">
              Bio — visible to patients booking with you
            </label>
            <textarea
              rows={3}
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              placeholder="e.g. 10 years in family medicine, fluent in Malay and Mandarin."
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm mb-2"
            />
            <label className="block text-xs font-medium text-slate-500 mb-1">
              Internal contact email — staff/admin only, not your login email
            </label>
            <input
              type="email"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm"
            />
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                onClick={saveProfile}
                disabled={profileBusy}
                className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
              >
                {profileBusy ? "Saving…" : "Save profile"}
              </button>
              {profileMsg && (
                <span className={`text-xs ${profileMsg === "Saved" ? "text-green-700" : "text-red-700"}`}>
                  {profileMsg}
                </span>
              )}
            </div>
          </div>
        </div>
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
