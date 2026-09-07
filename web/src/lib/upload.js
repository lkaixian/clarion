// Client-side medicine-photo validation -- an instant inline message before
// the upload is attempted. Returns an error string, or "" when acceptable.
// Extracted (code-review follow-up 2026-09-07) from identical copies in
// AdminConsole.jsx and Pharmacy.jsx.

export const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

export function validateImageFile(file) {
  if (!file) return "";
  if (!file.type.startsWith("image/")) return "That file isn't an image.";
  if (file.size > MAX_IMAGE_BYTES) return "Image must be 2MB or smaller.";
  return "";
}
