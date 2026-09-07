// Shared timestamp formatters. No date library in this codebase -- plain
// built-in Intl formatting, matching every timestamp rendered across the
// console. Extracted (code-review follow-up 2026-09-07) from byte-identical
// copies in AdminConsole / Pharmacy / WardMap / Reception / WaitingRoomDisplay.

export function formatDateTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function formatTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString() : "—";
}
