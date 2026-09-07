import { useEffect, useMemo, useState } from "react";
import { getCurrentUser, refreshCurrentUser } from "../api/client";

// A faint, tiled, diagonal overlay stamped across whatever it wraps —
// "<viewer name> · <patient id> · <viewed-at time>". It doesn't stop anyone
// copying data, but it makes a screenshot or phone photo of a patient
// record traceable back to the account that had it open. Screenshot
// traceability was the one copy-protection measure asked for.
//
// The viewer name is refreshed from the server (/auth/me) on mount rather
// than trusted from local storage alone — a user editing their cached
// `mb_user` could otherwise stamp SOMEONE ELSE's name onto their own
// screenshots (framing), which defeats the point. It's still their own
// authenticated identity (the token decides who /auth/me returns); it just
// can't be locally spoofed to another name.
//
// `position: fixed; inset: 0; pointer-events: none` so it covers the
// viewport, scrolls with nothing, and never intercepts a click. z-40 keeps
// it under the app's modals (z-50) so dialogs stay readable.
export default function Watermark({ patientId }) {
  const [viewerName, setViewerName] = useState(() => getCurrentUser()?.full_name || "");

  useEffect(() => {
    let cancelled = false;
    refreshCurrentUser()
      .then((u) => { if (!cancelled && u?.full_name) setViewerName(u.full_name); })
      .catch(() => { /* keep the cached name — the 401 interceptor handles a dead session */ });
    return () => { cancelled = true; };
  }, []);

  const backgroundImage = useMemo(() => {
    const label = [
      viewerName || "unknown viewer",
      patientId ? `patient ${patientId}` : null,
      `viewed ${new Date().toLocaleString()}`,
    ]
      .filter(Boolean)
      .join("  ·  ");

    // XML-escape for safe embedding in the SVG <text> node.
    const safe = label
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='540' height='320'>
      <text x='20' y='170' transform='rotate(-28 270 160)'
        fill='rgba(15,23,42,0.055)' font-size='16'
        font-family='system-ui, -apple-system, Segoe UI, sans-serif'>${safe}</text>
    </svg>`;

    return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
  }, [viewerName, patientId]);

  return (
    <div
      aria-hidden="true"
      className="fixed inset-0 z-40 pointer-events-none select-none"
      style={{ backgroundImage, backgroundRepeat: "repeat" }}
    />
  );
}
