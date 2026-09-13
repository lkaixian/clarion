// Shared "where does this user belong" logic, used by Login.jsx (post-login
// redirect), App.jsx (RequirePage route guard) and Layout.jsx (homeHref +
// which nav links to render).
//
// The backend now controls, per facility, which console "pages" each staff
// role may reach — the logged-in user object (cached as `mb_user`, read via
// getCurrentUser(), refreshed by refreshCurrentUser() / GET /auth/me) carries
// an `allowed_pages: string[]` drawn from ["patients","reception","pharmacy",
// "admin"]. A patient / emergency_responder gets `[]`; an admin always gets
// all four. Everything below is derived from that array so there's exactly
// one place to change the ordering/rules.

export const PAGE_ROUTE = {
  patients: "/patients",
  reception: "/reception",
  pharmacy: "/pharmacy",
  ancillary: "/ancillary",
  dental: "/dental",
  billing: "/billing",
  reporting: "/reporting",
  dashboard: "/dashboard",
  admin: "/admin",
};

// The landing page for a user right after login, for the "home" logo link,
// and the redirect target when a guard bounces someone off a page they can't
// open. Order = priority: admin console first, then the clinical desk, then
// reception, then ancillary, then dental, then billing, then pharmacy —
// billing isn't anyone's primary landing page (P3.3).
export function landingPathFor(user) {
  if (!user) return "/";
  // A patient account can't call GET /patients (the staff list) — their only
  // reachable page is their own record at /patients/{their patient_id}, which
  // the backend scopes correctly for them.
  if (user.role === "patient") return user.patient_id ? `/patients/${user.patient_id}` : "/";
  const pages = user.allowed_pages || [];
  if (pages.includes("admin")) return "/admin";
  if (pages.includes("patients")) return "/patients";
  if (pages.includes("reception")) return "/reception";
  if (pages.includes("ancillary")) return "/ancillary";
  if (pages.includes("dental")) return "/dental";
  if (pages.includes("billing")) return "/billing";
  if (pages.includes("reporting")) return "/reporting";
  if (pages.includes("dashboard")) return "/dashboard";
  if (pages.includes("pharmacy")) return "/pharmacy";
  return "/"; // staff with no pages at all — shouldn't happen, but don't crash
}
