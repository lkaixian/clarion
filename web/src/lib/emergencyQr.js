const PREFIX = "CLARION-EMERGENCY:";

// Card reference from a scanned emergency QR / NFC link: the legacy
// "CLARION-EMERGENCY:<ref>" text or a URL whose path is exactly /e/<ref> (any host).
// Anything else (including /e/n/... and malformed percent-encoding) returns null.
export function parseEmergencyQr(text) {
  const raw = (text || "").trim();
  if (raw.startsWith(PREFIX)) return raw.slice(PREFIX.length);
  const m = raw.match(/^https?:\/\/[^/?#\s]+\/e\/([^/?#\s]+)\/?(?:[?#].*)?$/i);
  if (!m) return null;
  try { return decodeURIComponent(m[1]); } catch { return null; }
}

// Where to go after sign-in. A forced password change always wins; ?next= is honoured
// only for a single-segment /e/<ref> path (no host, no extra segments, no newline).
export function afterLoginPath(user, search, landingPathFor) {
  if (user.must_change_password) return "/change-password";
  const next = new URLSearchParams(search).get("next");
  return next && /^\/e\/[\w-]+$/.test(next) ? next : landingPathFor(user);
}
