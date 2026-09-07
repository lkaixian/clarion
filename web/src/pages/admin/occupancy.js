// Occupancy thresholds for the proportional bar/badge below — this codebase
// has no charting library (see task constraints), so this is a plain
// Tailwind-colored div sized by percentage width. Colors extend the same
// amber="needs attention" / red="critical" vocabulary already established
// by the fasting-required callout and cancelled/revoked states elsewhere in
// this app, rather than introducing a new palette just for this bar.
export function occupancyColor(pct) {
  if (pct >= 90) return "bg-red-600";
  if (pct >= 75) return "bg-amber-500";
  return "bg-green-600";
}
export function occupancyTextColor(pct) {
  if (pct >= 90) return "text-red-700";
  if (pct >= 75) return "text-amber-700";
  return "text-green-700";
}
