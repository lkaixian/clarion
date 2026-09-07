// Turn a PNG data-URL (canvas.toDataURL("image/png") output) into a Blob so
// callers can POST it as multipart form-data. Also tolerates a bare base64
// string (no "data:...," prefix). Returns null for empty input.
//
// Lives here rather than in SignaturePad.jsx so that component file only
// exports a component (React Fast Refresh requirement / oxlint
// react/only-export-components). Consumed by SignaturePad and Profile.
export function dataUrlToPngBlob(dataUrl) {
  if (!dataUrl) return null;
  const comma = dataUrl.indexOf(",");
  const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: "image/png" });
}
