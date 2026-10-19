import { useEffect, useRef, useState } from "react";
import Layout from "../components/Layout";
import SignaturePad from "../components/SignaturePad";
import { roleLabel } from "../lib/role";
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
import { tr } from "../lib/i18n";

// Matches the backend limit in routers/profile.py (MAX_SIGNATURE_BYTES).
const MAX_SIGNATURE_BYTES = 500 * 1024;
const ACCEPTED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_IMAGE_EDGE = 900; // px: a signature never needs more, and it keeps the PNG small

// Reads a picture of a signature (PNG, JPEG or WebP) and returns it as a PNG data URL, scaled
// down if it is large. The server stores PNG only, so other formats are converted here.
function fileToPngDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
      reject(new Error("Choose a PNG, JPEG or WebP image."));
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, MAX_IMAGE_EDGE / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(img.width * scale));
      canvas.height = Math.max(1, Math.round(img.height * scale));
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL("image/png"));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file could not be read as an image."));
    };
    img.src = url;
  });
}

// Any authenticated staff member's own profile. Route is wrapped in
// <Protected> only (no RequirePage) — a signature isn't a "console page",
// every non-patient role needs one to complete consultations / sign off
// records.
export default function Profile() {
  const [user, setUser] = useState(() => getCurrentUser());
  const [sigUrl, setSigUrl] = useState(null);
  // Bumped after an upload so the load effects re-fetch when has_signature /
  // has_photo stay true (replacing an image doesn't flip the flag).
  const [sigVer, setSigVer] = useState(0);
  const [photoVer, setPhotoVer] = useState(0);
  const [replacing, setReplacing] = useState(false);
  const [draft, setDraft] = useState(null); // data-URL from the pad, or null
  const [uploadPreview, setUploadPreview] = useState(null); // data-URL of an uploaded picture, or null
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
  }, [hasSignature, sigVer]);

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
  }, [hasPhoto, photoVer]);

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
    window.dispatchEvent(new Event("mb-profile-updated")); // sidebar avatar re-fetches
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
      setPhotoVer((v) => v + 1);
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

  async function handlePickImage(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // the same file can be chosen again
    if (!file) return;
    setError("");
    try {
      const dataUrl = await fileToPngDataUrl(file);
      setDraft(dataUrl);
      setUploadPreview(dataUrl);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleSave() {
    const blob = dataUrlToPngBlob(draft);
    if (!blob) {
      setError("Draw your signature first.");
      return;
    }
    if (blob.size > MAX_SIGNATURE_BYTES) {
      setError("That signature image is too large. Draw a simpler one or use a smaller picture.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await uploadMySignature(blob);
      setSigVer((v) => v + 1);
      setDraft(null);
      setUploadPreview(null);
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
        <h1 className="page-title">{tr("Profile")}</h1>
        <p className="text-sm text-slate-500">
          Signed in as {user.full_name} · {roleLabel(user.role)}
          {user.facility ? ` · ${user.facility}` : ""}
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4 max-w-lg">
        <h2 className="font-semibold text-slate-800 mb-3">{tr("Your profile")}</h2>

        <div className="flex items-start gap-4 mb-4">
          <div className="shrink-0">
            {photoUrl ? (
              <img
                src={photoUrl}
                alt={tr("Your profile photo")}
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
              placeholder={tr("e.g. 10 years in family medicine, fluent in Malay and Mandarin.")}
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
                className="btn-primary"
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
        <h2 className="font-semibold text-slate-800 mb-3">{tr("Your signature")}</h2>
        {error && <div className="alert-error mb-3">{error}</div>}

        {hasSignature && !replacing ? (
          <>
            {sigUrl ? (
              <img
                src={sigUrl}
                alt={tr("Your saved signature")}
                className="border border-slate-200 rounded-lg bg-white"
                style={{ width: 360, height: 140, objectFit: "contain" }}
              />
            ) : (
              <p className="text-sm text-slate-400">{tr("Loading…")}</p>
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setReplacing(true);
                  setDraft(null);
                  setError("");
                }}
                className="btn-primary"
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
            <SignaturePad onChange={(d) => { setUploadPreview(null); setDraft(d); }} />
            <div className="mt-3">
              <label htmlFor="sig-upload" className="field-label">{tr("Or upload a picture of your signature")}</label>
              <input
                id="sig-upload" type="file" accept="image/png,image/jpeg,image/webp"
                onChange={handlePickImage} disabled={busy}
                className="block text-sm text-slate-700"
              />
              <p className="mt-1 text-xs text-slate-400">{tr("PNG, JPEG or WebP. Sign on plain white paper and crop close for the best result.")}</p>
            </div>
            {uploadPreview && (
              <div className="mt-3">
                <p className="text-xs text-slate-500 mb-1">{tr("Preview of the uploaded picture. Press Save to use it.")}</p>
                <img
                  src={uploadPreview} alt={tr("Uploaded signature preview")}
                  className="border border-slate-200 rounded-lg bg-white"
                  style={{ width: 360, height: 140, objectFit: "contain" }}
                />
              </div>
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={handleSave}
                disabled={busy || !draft}
                className="btn-primary"
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
                  className="btn-secondary"
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
