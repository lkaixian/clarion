// "clinician" -> "Clinician", "records_officer" -> "Records Officer".
// Roles are stored lowercase_snake; this is the one place they're made readable.
export const roleLabel = (role) => (role || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
