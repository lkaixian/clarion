import axios from "axios";

// Where the backend lives. Resolved once, at load, in this order:
//
//   1. window.__CLARION_API_BASE__  -- written by /config.js, which the
//      container's entrypoint.sh regenerates from the $API_BASE env var on
//      every start (see web/entrypoint.sh, web/nginx.conf). This is how a
//      single built image is pointed at a rotating Cloudflare-tunnel URL, or
//      at "/api" for the same-origin nginx proxy, with no rebuild.
//   2. import.meta.env.VITE_API_BASE  -- a build-time override for a dev who
//      runs `npm run dev` against a non-default backend.
//   3. http://localhost:8000  -- the local-dev default.
//
// A trailing slash is trimmed so `${API_BASE}/auth/login` is always clean,
// including the "/api" proxy case ("/api/" -> "/api").
function resolveApiBase() {
  const candidates = [
    typeof window !== "undefined" ? window.__CLARION_API_BASE__ : undefined,
    import.meta.env?.VITE_API_BASE,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim().replace(/\/+$/, "");
    }
  }
  // Nothing resolved. Fine in local dev; a misconfig in a real build --
  // /config.js failed to load or shipped empty and no VITE_API_BASE was
  // baked in. Make that loud rather than silently hitting localhost.
  if (import.meta.env?.PROD) {
    console.error(
      "[CLARION] No API base configured (window.__CLARION_API_BASE__ empty, " +
      "no VITE_API_BASE) -- falling back to http://localhost:8000. Check /config.js."
    );
  }
  return "http://localhost:8000";
}

export const API_BASE = resolveApiBase();

// P2.5 (Security Audit M4): `withCredentials: true` is what actually lets
// the browser send/receive the HttpOnly refresh-token cookie POST
// /auth/login sets (see backend/app/routers/auth_router.py's
// _set_refresh_cookie) -- without it, every cookie the backend sets is
// simply dropped by the browser on both same-origin (harmless, cookies
// aren't required there either way) and cross-origin calls (where it
// matters: the CORS response also needs Access-Control-Allow-Credentials,
// which main.py now only sends when an explicit CORS_ALLOWED_ORIGINS
// allowlist is configured -- never with the demo wildcard, which the CORS
// spec forbids combining with credentials anyway).
const client = axios.create({ baseURL: API_BASE, withCredentials: true });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("mb_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Any 401 that comes back through this client means the bearer token we
// just sent is no longer good — it could genuinely be expired (now a
// routine, frequent event: access tokens are 15 minutes, not 8 hours —
// see the refresh handling below, which transparently recovers from this
// exact case first) or it was invalidated some other way — a password
// change on another device/console (which now also revokes every refresh
// token for the account, see the backend's P2.5 work), or a real
// server-side logout elsewhere. Whatever page triggered the call has no
// way to recover from that by itself, so it's handled once here globally.
//
// EXCEPTION: POST /auth/login returns a 401 for the completely ordinary
// "wrong email/NRIC or password" case — that is NOT a session problem, and
// Login.jsx's own try/catch already turns it into a proper on-page error
// message. If this interceptor fired for that response too, the user would
// never see that message; they'd just get silently bounced back to the
// login page they're already sitting on. The OTP password-reset and
// refresh endpoints get the same exclusion defensively: the OTP ones
// require no bearer token to begin with and 400 (not 401) on bad input per
// the backend, and a 401 from /auth/refresh itself must fall straight
// through to the "give up" branch below rather than trying to refresh its
// own way out of failing.
const UNAUTHENTICATED_AUTH_PATHS = [
  "/auth/login",
  "/auth/request-password-reset-otp",
  "/auth/reset-password-with-otp",
  "/auth/refresh",
];

// Single-flight refresh: if several requests 401 around the same moment
// (e.g. a page that fires 3 API calls on mount, all with the same
// now-expired access token), they must all await the SAME refresh call
// rather than each independently racing the backend's single-use rotation
// -- the second caller to actually run POST /auth/refresh would present an
// already-rotated-away token and get treated as a reuse/compromise signal
// (see auth.rotate_refresh_token), revoking the whole session instead of
// just refreshing it.
let refreshInFlight = null;

function refreshAccessToken() {
  if (!refreshInFlight) {
    refreshInFlight = axios
      .post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true })
      .then(({ data }) => {
        localStorage.setItem("mb_token", data.access_token);
        localStorage.setItem("mb_user", JSON.stringify(data.user));
        return data.access_token;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

function bounceToLogin() {
  logout();
  // Full page reload (not react-router's useNavigate) is deliberate: this
  // module is plain JS imported outside the React tree, so there is no
  // navigate function reachable from here to call, and no component to
  // hook a redirect effect into. A hard reload also guarantees any
  // in-memory state left over from the now-dead session (cached user
  // object, component state, in-flight requests assuming the old token)
  // gets thrown away along with it, which a client-side-only redirect
  // wouldn't. Don't "simplify" this into useNavigate later — it isn't
  // reachable from a non-component module like this one.
  if (window.location.pathname !== "/") {
    window.location.href = "/";
  }
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const requestUrl = error.config?.url || "";
    const isUnauthenticatedAuthCall = UNAUTHENTICATED_AUTH_PATHS.some((path) => requestUrl.includes(path));

    if (error.response?.status === 401 && !isUnauthenticatedAuthCall) {
      // Try exactly once to silently recover via the refresh cookie before
      // giving up -- `_retriedAfterRefresh` guards against retrying a
      // request that was ALREADY retried once (refresh succeeded but the
      // retried call itself also 401'd for some other reason -- e.g. the
      // account was disabled between the two calls -- must not loop).
      if (!error.config?._retriedAfterRefresh) {
        try {
          const newAccessToken = await refreshAccessToken();
          error.config._retriedAfterRefresh = true;
          error.config.headers = { ...error.config.headers, Authorization: `Bearer ${newAccessToken}` };
          return client.request(error.config);
        } catch {
          // Refresh itself failed (no valid refresh token, or it was
          // revoked) -- fall through to the same "give up" handling a
          // pre-P2.5 expired token always got.
        }
      }
      bounceToLogin();
    }

    return Promise.reject(error);
  }
);

export async function login(email, password) {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  const { data } = await axios.post(`${API_BASE}/auth/login`, form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    withCredentials: true, // so the Set-Cookie refresh token is actually accepted
  });
  localStorage.setItem("mb_token", data.access_token);
  localStorage.setItem("mb_user", JSON.stringify(data.user));
  // `data.refresh_token` is deliberately NEVER read here (or anywhere else
  // in this file) -- it's a native-client-only field (see backend
  // schemas.Token's docstring); the web console's refresh token lives
  // ONLY in the HttpOnly cookie the browser already stored automatically,
  // never in JS-reachable storage.
  return data;
}

export function logout() {
  localStorage.removeItem("mb_token");
  localStorage.removeItem("mb_user");
  // Best-effort, fire-and-forget: revokes the refresh-token cookie
  // server-side (Security Audit M4 -- there was no real server-side
  // logout before P2.5). Never awaited/blocking -- the local state above
  // is cleared unconditionally regardless of whether this succeeds, since
  // the user-visible "am I logged out" state must never depend on a
  // network call succeeding.
  axios.post(`${API_BASE}/auth/logout`, {}, { withCredentials: true }).catch(() => {});
}

export function getCurrentUser() {
  const raw = localStorage.getItem("mb_user");
  return raw ? JSON.parse(raw) : null;
}

// Re-fetches the current user (e.g. after a profile edit changes
// missing_profile_fields) and refreshes the cached copy so getCurrentUser()
// reflects it without requiring a fresh login.
export async function refreshCurrentUser() {
  const { data } = await client.get("/auth/me");
  localStorage.setItem("mb_user", JSON.stringify(data));
  return data;
}

// Backend P2.2 (Security Audit H2): GET /patients now defaults to this
// staff member's OWN facility's known patients, paginated (limit defaults
// to 50 server-side, capped at 200). `limit: 200` here keeps this app's
// existing "fetch everyone, filter client-side" UI pattern working at its
// actual demo/clinic scale without a bigger pagination rework; `skip` is
// exposed for a future "load more" if a facility ever exceeds that.
// `breakGlassReason` is the explicit, audited override for a genuine
// cross-facility need (see PatientList.jsx) -- omit it to stay scoped.
export const listPatients = ({ skip, limit = 200, breakGlassReason } = {}) =>
  client
    .get("/patients", {
      params: {
        skip,
        limit,
        break_glass_reason: breakGlassReason || undefined,
      },
    })
    .then((r) => r.data);
export const createPatient = (payload) => client.post("/patients", payload).then((r) => r.data);
export const getPatient = (id) => client.get(`/patients/${id}`).then((r) => r.data);
export const addCondition = (id, payload) => client.post(`/patients/${id}/conditions`, payload).then((r) => r.data);
export const addMedication = (id, payload) => client.post(`/patients/${id}/medications`, payload).then((r) => r.data);
export const addAllergy = (id, payload) => client.post(`/patients/${id}/allergies`, payload).then((r) => r.data);
export const addEncounter = (id, payload) => client.post(`/patients/${id}/encounters`, payload).then((r) => r.data);
// Staff-only partial edits (fixing a typo'd dosage, correcting a visit
// reason after the fact, etc.) — separate from the add* calls above, which
// stay create-only. Each sends only the fields the form actually touched.
export const updateCondition = (id, conditionId, payload) => client.patch(`/patients/${id}/conditions/${conditionId}`, payload).then((r) => r.data);
export const updateMedication = (id, medicationId, payload) => client.patch(`/patients/${id}/medications/${medicationId}`, payload).then((r) => r.data);
export const updateAllergy = (id, allergyId, payload) => client.patch(`/patients/${id}/allergies/${allergyId}`, payload).then((r) => r.data);
export const updateEncounter = (id, encounterId, payload) => client.patch(`/patients/${id}/encounters/${encounterId}`, payload).then((r) => r.data);
export const getAuditLog = (id) => client.get(`/patients/${id}/audit-log`).then((r) => r.data);

// Document detail (raw OCR text + AI summary) is staff-only and deliberately
// left out of GET /patients/{id} (which only returns a lightweight summary
// list) so a normal patient-record fetch stays cheap. file_available tells
// you whether the ORIGINAL uploaded file (not just its OCR'd text) can be
// fetched — false for anything uploaded before file persistence existed.
export const getDocumentDetail = (id, documentId) => client.get(`/patients/${id}/documents/${documentId}`).then((r) => r.data);
// Fetched as a blob (not a plain <img src>/<a href>) because the endpoint
// requires the same Bearer auth as everything else here — a bare URL can't
// carry that header. Caller is responsible for revoking the object URL it
// builds from this when done with it.
export const getDocumentFileBlob = (id, documentId) =>
  client.get(`/patients/${id}/documents/${documentId}/file`, { responseType: "blob" }).then((r) => r.data);

// P3.5: generate a signed Digital Medical Certificate / Referral Letter /
// Timeslip PDF, filed as a ClinicalDocument (shows up in the same
// `documents` list/viewer as an uploaded scan — see getDocumentDetail/
// getDocumentFileBlob above).
export const generateDocument = (id, body) =>
  client.post(`/patients/${id}/documents/generate`, body).then((r) => r.data);

// P3.9: raw ESC/POS ticket bytes for a compatible printer --
// same Bearer-auth-needs-a-blob-fetch reasoning as getDocumentFileBlob.
export const getTicketPrintBlob = (ticketId) =>
  client.get(`/reception/queue/${ticketId}/ticket.escpos`, { responseType: "blob" }).then((r) => r.data);

// P3.9: a printable sample-label PNG for an ancillary order.
export const getServiceRequestLabelBlob = (requestId) =>
  client.get(`/ancillary/requests/${requestId}/label`, { responseType: "blob" }).then((r) => r.data);

export const getSummary = (id) => client.get(`/ai/summary/${id}`).then((r) => r.data);
export const getInteractionCheck = (id) => client.get(`/ai/interaction-check/${id}`).then((r) => r.data);
// P4.4: pre-save safety check for a medication not yet added --
// see the Add Medication modal in PatientDetail.jsx.
export const screenPrescription = (id, drugName) =>
  client.get(`/ai/prescription-screen/${id}?drug_name=${encodeURIComponent(drugName)}`).then((r) => r.data);
export const digitiseDocument = (id, docType, file) => {
  const form = new FormData();
  form.append("file", file);
  return client
    .post(`/ai/digitise/${id}?doc_type=${encodeURIComponent(docType)}`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const issueEmergencyCard = (patientId, scope) =>
  client.post("/emergency/issue", { patient_id: patientId, scope }).then((r) => r.data);
export const revokeEmergencyCard = (cardReference) =>
  client.post(`/emergency/revoke/${cardReference}`).then((r) => r.data);
// Read-only, no side effects — lets this console notice a card was
// issued/revoked/replaced elsewhere (e.g. from the patient's phone)
// without the admin having clicked "Issue Card" themselves. Poll this.
export const getCurrentCardStatus = (patientId) =>
  client.get(`/emergency/current/${patientId}`).then((r) => r.data);

// NFC physical cards — for senior citizens / anyone without a smartphone.
// Registration is staff-only; scanning (by a responder's NFC-capable
// phone) requires no auth, same design as the QR flow.
export const listNfcCards = (patientId) => client.get(`/emergency/nfc/${patientId}`).then((r) => r.data);
export const registerNfcCard = (patientId, nfcUid, scope) =>
  client.post("/emergency/nfc/register", { patient_id: patientId, nfc_uid: nfcUid, scope }).then((r) => r.data);
// Revoke by the grant id (from listNfcCards) -- the raw UID is stored
// hashed server-side and never returned to the client (Security Audit M7).
export const revokeNfcCard = (tokenId) => client.post(`/emergency/nfc/revoke/${tokenId}`).then((r) => r.data);

// Staff-only. Creates a login for a patient who doesn't have one yet, or
// regenerates the password of an existing one (doubles as staff-mediated
// password reset — same endpoint either way). Returns the plaintext temp
// password exactly once; the backend never stores or logs it in plaintext.
export const issuePatientAccount = (patientId) =>
  client.post(`/auth/patients/${patientId}/issue-account`).then((r) => r.data);

// Self-service reset, patient-only. Two steps: request a one-time code
// emailed to whatever contact email the patient has on file (step 1
// always responds the same way regardless of whether an account/email
// actually exists — don't treat a 200 as proof either way), then submit
// the code + new password (step 2). NRIC is accepted with or without
// dashes; the backend normalizes it.
export const requestPasswordResetOtp = (nationalId) =>
  axios.post(`${API_BASE}/auth/request-password-reset-otp`, { national_id: nationalId }).then((r) => r.data);
export const resetPasswordWithOtp = (nationalId, otpCode, newPassword) =>
  axios.post(`${API_BASE}/auth/reset-password-with-otp`, {
    national_id: nationalId, otp_code: otpCode, new_password: newPassword,
  }).then((r) => r.data);

// Patient self-service profile edit. Only email/phone/emergency-contact
// fields are accepted — full_name/date_of_birth/national_id are immutable
// via this endpoint and the backend 400s if they're present in the body.
export const updateOwnProfile = (patientId, payload) =>
  client.patch(`/patients/${patientId}/profile`, payload).then((r) => r.data);

// Scheduled appointments. GET is patient(own)+staff; POST/create and
// PATCH/update are staff-only on the backend (a patient viewer gets a 403,
// so the UI hides those actions rather than showing a dead-end button).
// scheduled_at is an ISO datetime string both ways — the caller is
// responsible for converting to/from whatever local input control it uses.
// `reminders` on the returned object is server-computed; never recompute it
// client-side.
export const getAppointments = (patientId) =>
  client.get(`/patients/${patientId}/appointments`).then((r) => r.data);
export const createAppointment = (patientId, payload) =>
  client.post(`/patients/${patientId}/appointments`, payload).then((r) => r.data);
// Partial update — {"status": "cancelled"} is how the UI cancels one.
export const updateAppointment = (patientId, appointmentId, payload) =>
  client.patch(`/patients/${patientId}/appointments/${appointmentId}`, payload).then((r) => r.data);

// Facility-scoped admin console (routers/admin.py) — every one of these is
// `role === "admin"`-only on the backend, and every response is already
// scoped server-side to the admin's own facility; the client never sends a
// facility_name anywhere below because there is nowhere in these payloads
// to put one (create schemas deliberately have no such field).
//
// Appointments dashboard — read-only monitoring across every patient at
// this admin's hospital. include_all mirrors the backend's default
// (status="scheduled" only) vs. the full history view.
export const getAdminAppointments = (includeAll) =>
  client.get("/admin/appointments", { params: { include_all: !!includeAll } }).then((r) => r.data);

// Medicine inventory. is_low_stock on each row is server-computed (see
// MedicineInventoryOut) — never re-derive it client-side. `q` is the shared
// search filter (drug-name substring OR barcode exact/prefix,
// case-insensitive); omit it for the full list.
export const getAdminInventory = ({ lowStockOnly = false, q } = {}) => {
  const params = {};
  if (lowStockOnly) params.low_stock_only = true;
  if (q) params.q = q;
  return client.get("/admin/inventory", { params }).then((r) => r.data);
};
export const createInventoryItem = (payload) => client.post("/admin/inventory", payload).then((r) => r.data);
// Partial update — used both for the full edit modal and the quick +/-
// restock stepper (which sends just {quantity_on_hand}).
export const updateInventoryItem = (itemId, payload) => client.patch(`/admin/inventory/${itemId}`, payload).then((r) => r.data);
export const deleteInventoryItem = (itemId) => client.delete(`/admin/inventory/${itemId}`).then((r) => r.data);

// Pharmacy stock (routers/pharmacy.py) — pharmacist OR admin. Pharmacists
// adjust stock volume and file catalogue-deletion requests; they cannot
// create/edit catalogue items or open patient records. adjustStock's delta
// is signed: > 0 restock (accrues procurement spend at unit_cost), < 0
// dispense (no budget effect, 400 if it would go negative). unit_cost /
// pending_delete_request on each returned item are server-computed.
// `q` (optional): drug-name substring OR barcode exact/prefix,
// case-insensitive — a hardware barcode scanner just types the code then
// sends Enter into the search box. Omit for the full list.
export const getPharmacyInventory = ({ q } = {}) =>
  client.get("/pharmacy/inventory", { params: q ? { q } : {} }).then((r) => r.data);
// Low-stock rows only (server-side filter — same predicate as is_low_stock).
export const getLowStockInventory = () =>
  client.get("/pharmacy/inventory/low-stock").then((r) => r.data);
// { low_stock_count, pending_proposal_count } — the two counters the
// pharmacy console badges on load.
export const getPharmacySummary = () =>
  client.get("/pharmacy/summary").then((r) => r.data);
// Returns the RAW axios response (not just .data): a restock (delta > 0) on
// an item that is NOT auto_approved comes back as HTTP 202 with a
// PurchaseProposalOut body instead of 200 + MedicineInventoryOut, so the
// caller has to branch on `response.status` to tell "stock changed" from
// "proposal filed for admin approval". A duplicate identical pending
// proposal is a 409 (rejected promise).
export const adjustStock = (itemId, payload) =>
  client.post(`/pharmacy/inventory/${itemId}/adjust`, payload);
export const requestInventoryDeletion = (itemId, payload) =>
  client.post(`/pharmacy/inventory/${itemId}/delete-request`, payload || {}).then((r) => r.data);

// Purchase proposals — the pharmacist's own view (this facility's proposals,
// newest first). status: "pending" | "approved" | "rejected" | "all".
export const getPharmacyProposals = (status = "pending") =>
  client.get("/pharmacy/purchase-proposals", { params: { status } }).then((r) => r.data);
// Propose a BRAND-NEW catalogue item (restocking an existing item goes
// through adjustStock instead). 202 + PurchaseProposalOut on success; 409 if
// this requester already has an identical pending proposal (same name).
export const createPurchaseProposal = (body) =>
  client.post("/pharmacy/purchase-proposals", body).then((r) => r.data);

// Admin review queue for purchase proposals (facility-scoped server-side).
export const getAdminProposals = (status = "pending") =>
  client.get("/admin/purchase-proposals", { params: { status } }).then((r) => r.data);
// Approve applies the restock (existing item) or creates the item then
// restocks it (new item) — so the inventory list must be refetched after.
export const approvePurchaseProposal = (id) =>
  client.post(`/admin/purchase-proposals/${id}/approve`).then((r) => r.data);
export const rejectPurchaseProposal = (id, reason) =>
  client.post(`/admin/purchase-proposals/${id}/reject`, { reason: reason || null }).then((r) => r.data);

// Multipart medicine-photo upload (field name `file`, PNG/JPEG/WebP, ≤2MB —
// the backend re-checks content-type + extension + magic bytes and 422s if
// they disagree). `admin` picks the admin route vs the pharmacist one; same
// action, different role guard. Returns the updated MedicineInventoryOut.
export const uploadMedicineImage = (itemId, file, { admin = false } = {}) => {
  const form = new FormData();
  form.append("file", file);
  const path = admin
    ? `/admin/inventory/${itemId}/image`
    : `/pharmacy/inventory/${itemId}/image`;
  return client
    .post(path, form, { headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};
// The medicine photo endpoint needs the same Bearer auth as everything else,
// so it can't go straight in an <img src>. Fetch it as a blob and hand back
// an object URL (same pattern as getDocumentFileBlob); the caller is
// responsible for revoking that URL when the row unmounts. `imageUrl` is the
// path straight off MedicineInventoryOut.image_url.
export const getMedicineImageBlob = (imageUrl) =>
  client.get(imageUrl, { responseType: "blob" }).then((r) => URL.createObjectURL(r.data));

// Inventory deletion-request review + medicine procurement budget — both
// admin-only (routers/admin.py). getDeleteRequests defaults to the pending
// queue. approveDeleteRequest performs the hard delete of the item.
export const getDeleteRequests = (status = "pending") =>
  client.get("/admin/inventory/delete-requests", { params: { status } }).then((r) => r.data);
export const approveDeleteRequest = (id) =>
  client.post(`/admin/inventory/delete-requests/${id}/approve`).then((r) => r.data);
export const rejectDeleteRequest = (id, payload) =>
  client.post(`/admin/inventory/delete-requests/${id}/reject`, payload || {}).then((r) => r.data);
export const getBudget = () => client.get("/admin/budget").then((r) => r.data);
export const setBudget = (payload) => client.put("/admin/budget", payload).then((r) => r.data);

// Facility profile + the CLARION network records-sharing switch
// (routers/admin.py). The settings row is lazily created with defaults on
// the first GET (timezone "Asia/Kuala_Lumpur", records_shared_publicly true,
// display_name seeded to the facility name), so this never 404s. PUT accepts
// any subset of {display_name, address, contact_phone, timezone,
// records_shared_publicly} and rejects unknown keys — send only what changed.
export const getHospitalSettings = () => client.get("/admin/hospital-settings").then((r) => r.data);
export const updateHospitalSettings = (body) => client.put("/admin/hospital-settings", body).then((r) => r.data);

// P3.10: clinic-published notices the mobile app polls for.
export const listAnnouncements = () => client.get("/admin/announcements").then((r) => r.data);
export const createAnnouncement = (body) => client.post("/admin/announcements", body).then((r) => r.data);
export const deleteAnnouncement = (id) => client.delete(`/admin/announcements/${id}`).then((r) => r.data);

// Per-facility role → console-page access matrix (routers/admin.py, admin-only).
// GET returns one entry per configurable staff role (clinician, records_officer,
// receptionist, pharmacist — each `editable: true`) plus a read-only `admin`
// entry (`editable: false`, always full access). Each entry carries
// `allowed_pages` (the role's current access) and `configurable_pages` (the
// editable column set — always ["patients","reception","pharmacy"]; `admin` is
// never an editable cell).
//
// PUT accepts either a single `{ role, allowed_pages }` or an array of them
// (bulk — used by the "Save changes" button). `role` must be a configurable
// staff role; every page must be in ["patients","reception","pharmacy"].
// Returns the full refreshed array. 400 on an invalid role/page.
//
// NOTE: a user's cached `allowed_pages` only refreshes on login / GET /auth/me,
// so edits here take effect for a given user the next time they sign in.
export const getRolePermissions = () => client.get("/admin/role-permissions").then((r) => r.data);
export const updateRolePermissions = (body) => client.put("/admin/role-permissions", body).then((r) => r.data);

// Ward / bed capacity. occupancy_pct and available_beds are server-computed
// (see WardOut) — never re-derive them client-side.
export const getWards = () => client.get("/admin/wards").then((r) => r.data);
export const createWard = (payload) => client.post("/admin/wards", payload).then((r) => r.data);
// Partial update — used both for the full edit modal and the quick +/-
// occupied-beds stepper (which sends just {occupied_beds}).
export const updateWard = (wardId, payload) => client.patch(`/admin/wards/${wardId}`, payload).then((r) => r.data);
export const deleteWard = (wardId) => client.delete(`/admin/wards/${wardId}`).then((r) => r.data);

// Floors (admin-managed, facility-scoped like wards). A floor auto-generates
// `ward_count` uniform general wards of `beds_per_ward` beds each; the
// backend adds/removes/resizes those child wards on PATCH. total_beds /
// occupied_beds / ward_ids on each row are server-computed — never re-derive.
export const getFloors = () => client.get("/admin/floors").then((r) => r.data);
export const createFloor = (payload) => client.post("/admin/floors", payload).then((r) => r.data);
export const updateFloor = (floorId, payload) => client.patch(`/admin/floors/${floorId}`, payload).then((r) => r.data);
export const deleteFloor = (floorId) => client.delete(`/admin/floors/${floorId}`).then((r) => r.data);

// Per-bed admissions + the nested Ward Map (routers/reception.py). Any staff
// role (admin/clinician/records_officer), same as the rest of reception.
// admitPatient takes exactly one of { patient_id, national_id } plus an
// optional { floor_id } (auto-assign) or { ward_id, bed_number } (exact
// bed). The Admission id on each ward-map bed drives discharge/move.
export const getWardMap = () => client.get("/reception/ward-map").then((r) => r.data);
export const getAdmissions = (active = true) =>
  client.get("/reception/admissions", { params: { active } }).then((r) => r.data);
export const admitPatient = (payload) => client.post("/reception/admissions", payload).then((r) => r.data);
export const updateAdmission = (admissionId, payload) =>
  client.patch(`/reception/admissions/${admissionId}`, payload).then((r) => r.data);
export const dischargeAdmission = (admissionId) =>
  client.post(`/reception/admissions/${admissionId}/discharge`).then((r) => r.data);

// Staff clock-in/out. Any staff role (admin/clinician/records_officer) —
// not available to a patient account. All three return the same
// ClockStatusOut shape, so callers can just setState() straight from the
// response instead of re-fetching status separately after a mutation.
export const getClockStatus = () => client.get("/staff/clock-status").then((r) => r.data);
export const clockIn = () => client.post("/staff/clock-in").then((r) => r.data);
export const clockOut = () => client.post("/staff/clock-out").then((r) => r.data);

// Admin-only facility staff roster + per-staff clock history. History is
// fetched on demand per staff member (not eagerly for the whole roster) —
// callers should only call this when a row is actually expanded.
export const getStaffRoster = () => client.get("/admin/staff").then((r) => r.data);
export const getStaffClockHistory = (userId) => client.get(`/admin/staff/${userId}/clock-history`).then((r) => r.data);
// Partial staff edit — currently only `{ section: string | null }` (pin a
// receptionist/clinician to a front-desk counter, or null to unpin). 400 if
// the user isn't a receptionist/clinician or the section name isn't an
// active section at this facility. Returns the updated StaffRosterEntryOut.
export const updateStaffMember = (userId, body) => client.patch(`/admin/staff/${userId}`, body).then((r) => r.data);

// Front-desk registration sections ("counters") — admin-managed,
// facility-scoped like rooms/wards. GET returns active + inactive,
// name-ordered. createSection/updateSection 409 on a duplicate/clashing
// name. deleteSection also unassigns any staff pinned to it, backend-side.
export const getSections = () => client.get("/admin/sections").then((r) => r.data);
export const createSection = (body) => client.post("/admin/sections", body).then((r) => r.data);
export const updateSection = (id, body) => client.patch(`/admin/sections/${id}`, body).then((r) => r.data);
export const deleteSection = (id) => client.delete(`/admin/sections/${id}`).then((r) => r.data);

// Consultation rooms ("Bilik") — admin-managed, facility-scoped like wards.
// waiting_today on each row is server-computed; never re-derive it.
export const getRooms = () => client.get("/admin/rooms").then((r) => r.data);
export const createRoom = (payload) => client.post("/admin/rooms", payload).then((r) => r.data);
export const updateRoom = (roomId, payload) => client.patch(`/admin/rooms/${roomId}`, payload).then((r) => r.data);
export const deleteRoom = (roomId) => client.delete(`/admin/rooms/${roomId}`).then((r) => r.data);

// Reception desk check-in + queue system (routers/reception.py). Staff-only
// (admin/clinician/records_officer) except getQueueStatus, which a patient
// can also call for their own patient_id. checkin's payload must contain
// exactly one of patient_id/card_reference/nfc_uid — the backend 422s
// otherwise (see schemas.ReceptionCheckinRequest); callers here just pass
// through whatever the form actually filled in.
export const checkinToQueue = (payload) => client.post("/reception/checkin", payload).then((r) => r.data);
// Today's queue for the calling staff member's own facility (server-scoped,
// never client-supplied) — includes now_serving/waiting_count, both
// server-computed; never re-derive them client-side.
export const getQueue = () => client.get("/reception/queue").then((r) => r.data);
export const callNextTicket = (ticketId) => client.post(`/reception/queue/${ticketId}/call`).then((r) => r.data);
export const completeTicket = (ticketId) => client.post(`/reception/queue/${ticketId}/complete`).then((r) => r.data);
export const cancelTicket = (ticketId) => client.post(`/reception/queue/${ticketId}/cancel`).then((r) => r.data);
// `{"active": false}` when the patient has no waiting/called ticket today —
// same convention as getCurrentCardStatus above.
export const getQueueStatus = (patientId) => client.get(`/reception/queue/status/${patientId}`).then((r) => r.data);

// Self-check-in QR "station" — a facility-scoped, staff-generated QR that
// patients scan on-site to check themselves into today's queue without a
// staff member typing in their identifier. Staff-only (admin/clinician/
// records_officer), same as the rest of reception.py above. Only one
// station can be active per facility at a time; createStation is used for
// both first-time generation and regeneration (the backend revokes
// whatever was previously active for the caller's facility before creating
// the new one). qr_base64 is a ready-to-use `data:image/png;base64,...`
// string — no extra encoding needed before putting it in an <img src=...>.
export const getStation = () => client.get("/reception/station").then((r) => r.data);
export const createStation = (payload) => client.post("/reception/station", payload).then((r) => r.data);
export const revokeStation = () => client.post("/reception/station/revoke").then((r) => r.data);

// Active front-desk section names for the caller's facility (any reception
// staff, not admin-only — the admin-only /admin/sections above is the CRUD
// surface). Returns [] when the facility has no sections defined; Reception
// falls back to a hardcoded list in that case.
export const getReceptionSections = () => client.get("/reception/sections").then((r) => r.data);

// Manually override which consultation room a queue ticket is routed to
// (round-robin at check-in only picks a starting room).
export const assignTicketRoom = (ticketId, roomId) =>
  client.post(`/reception/queue/${ticketId}/assign-room`, { room_id: roomId }).then((r) => r.data);

// Clinician "My Room" worklist. getReceptionRooms lists the facility's
// active Bilik + who holds each; claim/release manage the caller's own
// claim (claim requires being clocked in); getMyRoom returns the room's
// today tickets — empty unless the caller is BOTH clocked in and holds a
// claim (the "withdrawn on clock-out" rule).
export const getReceptionRooms = () => client.get("/reception/rooms").then((r) => r.data);
export const claimRoom = (roomId) => client.post(`/reception/rooms/${roomId}/claim`).then((r) => r.data);
export const releaseRoom = () => client.post("/reception/rooms/release").then((r) => r.data);
export const getMyRoom = () => client.get("/reception/my-room").then((r) => r.data);

// Appointment reschedule (staff-only) + the patient's own reschedule
// *requests* (filed from the mobile app; web's job is only to show them and
// let staff accept/reject while pending — see reason code comments in
// PatientDetail.jsx's AppointmentsSection). Only valid while the
// appointment's status is "scheduled". new_scheduled_at is an ISO datetime
// string, same convention as createAppointment's scheduled_at above.
export const rescheduleAppointment = (patientId, appointmentId, payload) =>
  client.post(`/patients/${patientId}/appointments/${appointmentId}/reschedule`, payload).then((r) => r.data);
// Accepting a request does NOT change the appointment's time by itself —
// it only records that staff will call the patient to agree a new time;
// staff then use rescheduleAppointment above once a time is actually agreed.
export const acceptRescheduleRequest = (patientId, appointmentId, requestId) =>
  client.post(`/patients/${patientId}/appointments/${appointmentId}/reschedule-requests/${requestId}/accept`).then((r) => r.data);
export const rejectRescheduleRequest = (patientId, appointmentId, requestId, payload) =>
  client.post(`/patients/${patientId}/appointments/${appointmentId}/reschedule-requests/${requestId}/reject`, payload).then((r) => r.data);

// --- Digital signatures + clinical-record sign-off (annotations) ---------
// Every signature GET needs the same Bearer auth as the rest of this client,
// so a bare <img src> can't fetch it — they're pulled as blobs and handed
// back as object URLs (same pattern as getDocumentFileBlob / medicine
// images). The caller owns revoking that URL when its component unmounts.
// "No signature on file" is a deliberate 404 on the backend — resolve to
// null in that one case so callers render an empty state, not an error.
const signatureBlobUrl = (path) =>
  client
    .get(path, { responseType: "blob" })
    .then((r) => URL.createObjectURL(r.data))
    .catch((e) => {
      if (e?.response?.status === 404) return null;
      throw e;
    });

export const getMySignatureBlob = () => signatureBlobUrl("/me/signature");

export const uploadMySignature = (blob) => {
  const form = new FormData();
  // The filename MUST end .png — the backend cross-checks extension +
  // content-type + PNG magic bytes and 400s if any of the three disagree.
  form.append("file", blob, "signature.png");
  return client
    .post("/me/signature", form, { headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};

export const deleteMySignature = () => client.delete("/me/signature").then((r) => r.data);

export const getStaffSignatureBlob = (userId) => signatureBlobUrl(`/staff/${userId}/signature`);

export const getAnnotationSignatureBlob = (patientId, annotationId) =>
  signatureBlobUrl(`/patients/${patientId}/annotations/${annotationId}/signature`);

export const getPatientAnnotations = (patientId) =>
  client.get(`/patients/${patientId}/annotations`).then((r) => r.data);

// body: { target_type, target_id, kind, note?, signature_b64? }. Only send
// signature_b64 as a fallback when the caller has no saved signature
// (getCurrentUser().has_signature === false) — it also saves that drawing to
// their profile. The backend's b64 decoder wants RAW base64, so strip any
// "data:image/png;base64," prefix a <canvas> produced before sending.
export const addPatientAnnotation = (patientId, body) => {
  const payload = { ...body };
  if (typeof payload.signature_b64 === "string" && payload.signature_b64.startsWith("data:")) {
    const comma = payload.signature_b64.indexOf(",");
    if (comma >= 0) payload.signature_b64 = payload.signature_b64.slice(comma + 1);
  }
  return client.post(`/patients/${patientId}/annotations`, payload).then((r) => r.data);
};

// --- Clinician consultation panel (routers/consultation.py) -------------
// Roles admin/records_officer/clinician, gated by require_page_access("patients").
// session/start clocks the caller in AND claims the room in one call;
// session/end reverses both. tickets/{id}/complete needs a signature — the
// caller passes signature_b64 as RAW base64 (strip the data-URL prefix)
// only as a fallback when getCurrentUser().has_signature is false.
export const getConsultationRooms = () => client.get("/consultation/rooms").then((r) => r.data);
export const getMyConsultationRoom = () => client.get("/consultation/my-room").then((r) => r.data);
export const startConsultationSession = (body) => client.post("/consultation/session/start", body).then((r) => r.data);
export const endConsultationSession = () => client.post("/consultation/session/end").then((r) => r.data);
export const callConsultationTicket = (id) => client.post(`/consultation/tickets/${id}/call`).then((r) => r.data);
export const completeConsultationTicket = (id, body) =>
  client.post(`/consultation/tickets/${id}/complete`, body || {}).then((r) => r.data);
export const cancelConsultationTicket = (id) =>
  client.post(`/consultation/tickets/${id}/cancel`).then((r) => r.data);
// P4.3b — advisory only, nothing persisted; safe to call repeatedly while
// drafting the note. body: {subjective, objective, assessment, plan}, any
// may be omitted.
export const getCdsHint = (id, body) =>
  client.post(`/consultation/tickets/${id}/cds-hint`, body || {}).then((r) => r.data);
// P4.3c — dictation blob in, {transcript, soap} back. Same
// nothing-persisted, advisory-only contract as getCdsHint above.
export const getVoiceToSoap = (id, audioBlob) => {
  const form = new FormData();
  form.append("file", audioBlob, "dictation.webm");
  return client
    .post(`/consultation/tickets/${id}/voice-to-soap`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

// --- Waiting-room displays ---------------------------------------------
// getWaitingRoomDisplays/create/revoke are admin-only (routers/admin.py).
// getPublicDisplay hits the UNAUTHENTICATED, rate-limited /display/{token}
// endpoint — it deliberately uses a bare axios call (not the shared
// `client` instance) so the request interceptor never attaches the bearer
// token: a public big-screen page has no logged-in user.
export const getWaitingRoomDisplays = () => client.get("/admin/waiting-room-displays").then((r) => r.data);
export const createWaitingRoomDisplay = (body) => client.post("/admin/waiting-room-displays", body).then((r) => r.data);
export const revokeWaitingRoomDisplay = (id) =>
  client.post(`/admin/waiting-room-displays/${id}/revoke`).then((r) => r.data);
export const getPublicDisplay = (token) =>
  axios.get(`${API_BASE}/display/${token}`).then((r) => r.data);

// --- Ancillary engine: Procedure / Laboratory / X-ray / Physiotherapy
// (P3.1, routers/ancillary.py) --------------------------------------------
// One shared order -> result -> sign-off -> document pipeline behind all
// four modules; `module` is just a value ("procedure" | "laboratory" |
// "xray" | "physiotherapy"), not a separate API. Gated by
// require_page_access("ancillary"); sign-off/catalog-write additionally
// need admin/records_officer/clinician server-side (see
// SIGNOFF_ROLES in ancillary.py) — receptionist can place/cancel orders
// only.
export const getAncillaryCatalog = ({ module, includeInactive } = {}) =>
  client
    .get("/ancillary/catalog", { params: { module, include_inactive: includeInactive || undefined } })
    .then((r) => r.data);
export const createAncillaryCatalogItem = (body) => client.post("/ancillary/catalog", body).then((r) => r.data);
export const updateAncillaryCatalogItem = (itemId, body) =>
  client.patch(`/ancillary/catalog/${itemId}`, body).then((r) => r.data);

export const listAncillaryRequests = ({ module, status, patientId, limit, offset } = {}) =>
  client
    .get("/ancillary/requests", { params: { module, status, patient_id: patientId, limit, offset } })
    .then((r) => r.data);
export const getAncillaryRequest = (requestId) => client.get(`/ancillary/requests/${requestId}`).then((r) => r.data);
// body: { patient_id, module, catalog_item_id, source, source_encounter_id?,
// clinical_indication?, priority? }. source_encounter_id is required when
// source === "physician_order".
export const createAncillaryRequest = (body) => client.post("/ancillary/requests", body).then((r) => r.data);
export const cancelAncillaryRequest = (requestId, reason) =>
  client.post(`/ancillary/requests/${requestId}/cancel`, { reason }).then((r) => r.data);

// body: { result_text?, flag_abnormal?, flag_critical?, signature_b64? }.
// Same "strip the data: URL prefix, only send as a fallback when the caller
// has no saved signature" rule as addPatientAnnotation/
// completeConsultationTicket above.
export const signOffAncillaryResult = (requestId, body) => {
  const payload = { ...body };
  if (typeof payload.signature_b64 === "string" && payload.signature_b64.startsWith("data:")) {
    const comma = payload.signature_b64.indexOf(",");
    if (comma >= 0) payload.signature_b64 = payload.signature_b64.slice(comma + 1);
  }
  return client.post(`/ancillary/requests/${requestId}/result`, payload).then((r) => r.data);
};
export const uploadAncillaryResultDocument = (requestId, file) => {
  const form = new FormData();
  form.append("file", file);
  return client
    .post(`/ancillary/requests/${requestId}/result/document`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};
// Fetched as a blob (Bearer-authed, same reasoning as getDocumentFileBlob
// above) — caller revokes the object URL when done with it.
export const getAncillaryResultDocumentBlob = (requestId) =>
  client.get(`/ancillary/requests/${requestId}/result/document`, { responseType: "blob" }).then((r) => r.data);

export const getAncillaryStats = () => client.get("/ancillary/stats").then((r) => r.data);

// P4.7 PACS/DICOM imaging -- sits on top of an xray ServiceRequest
// (routers/pacs.py). `dicomInstanceFileUrl` is a plain URL string, not an
// axios call: DicomViewer.jsx hands it straight to dwv's `loadURLs`, which
// fetches each instance itself (with an Authorization header dwv attaches
// via its own `requestHeaders` option) -- there's no blob step here.
export const uploadDicomStudy = (requestId, file) => {
  const form = new FormData();
  form.append("file", file);
  return client
    .post(`/pacs/requests/${requestId}/study`, form, { headers: { "Content-Type": "multipart/form-data" } })
    .then((r) => r.data);
};
export const getDicomStudy = (requestId) => client.get(`/pacs/requests/${requestId}/study`).then((r) => r.data);
export const dicomInstanceFileUrl = (requestId, instanceId) =>
  `${API_BASE}/pacs/requests/${requestId}/study/instances/${instanceId}/file`;

// P3.2 Dental module. Only the tooth chart is a dedicated API here --
// queue/appointments reuse Reception, X-ray references reuse
// createAncillaryRequest (module: "xray"), medication reuses
// add/updateMedication, diagnosis reuses add/updateCondition. Gated by
// require_page_access("dental"); CHART_ROLES server-side
// (admin/records_officer/clinician) -- no receptionist.
export const getDentalChartOptions = () => client.get("/dental/chart-options").then((r) => r.data);
export const getDentalChart = (patientId, { limit, offset } = {}) =>
  client.get(`/dental/chart/${patientId}`, { params: { limit, offset } }).then((r) => r.data);
// body: { patient_id, encounter_id?, tooth_code, finding, treatment?, notes?,
// signature_b64? }. Create-with-signature IS the sign-off --
// same "strip the data: URL prefix" rule as signOffAncillaryResult above.
export const createDentalChartEntry = (body) => {
  const payload = { ...body };
  if (typeof payload.signature_b64 === "string" && payload.signature_b64.startsWith("data:")) {
    const comma = payload.signature_b64.indexOf(",");
    if (comma >= 0) payload.signature_b64 = payload.signature_b64.slice(comma + 1);
  }
  return client.post("/dental/chart", payload).then((r) => r.data);
};

// Billing (P3.3, routers/billing.py): charge master / bills / bill_items /
// payments / claims. Facility-local only — unlike Ancillary/Dental there is
// no cross-facility read mode at all. Every BillItem price is
// server-derived (see billing.py's module docstring) — the client NEVER
// sends a price, only a source reference + quantity. Gated by
// require_page_access("billing"); write endpoints additionally need
// admin/records_officer/receptionist server-side (BILLING_WRITE_ROLES),
// claims need admin/records_officer (CLAIM_ROLES) — clinician/pharmacist
// get read-only access.
export const getChargeMasterItems = ({ category, includeInactive } = {}) =>
  client
    .get("/billing/charge-master", { params: { category, include_inactive: includeInactive || undefined } })
    .then((r) => r.data);
export const createChargeMasterItem = (body) => client.post("/billing/charge-master", body).then((r) => r.data);
export const updateChargeMasterItem = (itemId, body) =>
  client.patch(`/billing/charge-master/${itemId}`, body).then((r) => r.data);

// body: { patient_id, encounter_id? }.
export const createBill = (body) => client.post("/billing/bills", body).then((r) => r.data);
export const listBills = ({ patientId, status, limit, offset } = {}) =>
  client.get("/billing/bills", { params: { patient_id: patientId, status, limit, offset } }).then((r) => r.data);
export const getBill = (billId) => client.get(`/billing/bills/${billId}`).then((r) => r.data);

// body: { source_type: "charge_master"|"service_request"|"pharmacy_item",
// charge_master_item_id? | service_request_id? | medicine_inventory_item_id?,
// quantity? }. Exactly one of the three ids must match source_type — no price
// field, the server derives it (see billing.py's module docstring).
export const addBillItem = (billId, body) => client.post(`/billing/bills/${billId}/items`, body).then((r) => r.data);
export const voidBillItem = (billId, itemId, reason) =>
  client.post(`/billing/bills/${billId}/items/${itemId}/void`, { reason }).then((r) => r.data);
export const finalizeBill = (billId) => client.post(`/billing/bills/${billId}/finalize`).then((r) => r.data);
export const voidBill = (billId, reason) => client.post(`/billing/bills/${billId}/void`, { reason }).then((r) => r.data);

// body: { amount_cents, method: "cash"|"card"|"insurance"|"panel"|"other",
// reference_no?, claim_id? }. claim_id requires method "insurance"/"panel".
export const recordPayment = (billId, body) =>
  client.post(`/billing/bills/${billId}/payments`, body).then((r) => r.data);
export const voidPayment = (paymentId, reason) =>
  client.post(`/billing/payments/${paymentId}/void`, { reason }).then((r) => r.data);

// Claims — admin/records_officer only server-side. `claim_amount_cents`
// may be less than the bill's total (the copay/split model) but never more
// than its current unclaimed balance (patient_due_cents -- net of every
// OTHER submitted/approved claim; the server 400s otherwise). There is no
// standalone "mark paid" action -- a claim moves to "paid" only via a
// linked Payment (recordPayment's `claim_id`), so "paid" always has a real
// amount behind it.
export const createClaim = (billId, body) => client.post(`/billing/bills/${billId}/claims`, body).then((r) => r.data);
export const updateClaim = (claimId, body) => client.patch(`/billing/claims/${claimId}`, body).then((r) => r.data);
export const submitClaim = (claimId) => client.post(`/billing/claims/${claimId}/submit`).then((r) => r.data);
export const approveClaim = (claimId) => client.post(`/billing/claims/${claimId}/approve`).then((r) => r.data);
export const rejectClaim = (claimId, reason) =>
  client.post(`/billing/claims/${claimId}/reject`, { reason }).then((r) => r.data);
export const voidClaim = (claimId, reason) =>
  client.post(`/billing/claims/${claimId}/void`, { reason }).then((r) => r.data);

export const getBillingStats = () => client.get("/billing/stats").then((r) => r.data);

// Reporting (P3.6, routers/reporting.py): canned reports + Custom Report
// Builder. Facility-local only, same as Billing. `getReportDatasets()` is
// the field-picker catalogue the builder UI renders itself from — never a
// hardcoded field list on the client (see reporting_engine.py's docstring
// for why: a client-supplied field name is validated dataset-side, never
// reaches raw SQL). `exportReport` returns a Blob (responseType) — the
// caller turns it into an object URL, same convention as
// getDocumentFileBlob elsewhere in this file.
export const getReportDatasets = () => client.get("/reports/datasets").then((r) => r.data);
export const runReport = (body) => client.post("/reports/run", body).then((r) => r.data);
export const exportReport = (body) =>
  client.post("/reports/export", body, { responseType: "blob" }).then((r) => r.data);
export const narrateReport = (body) => client.post("/reports/narrative", body).then((r) => r.data);

export const listReportTemplates = (dataset) =>
  client.get("/reports/templates", { params: { dataset: dataset || undefined } }).then((r) => r.data);
export const createReportTemplate = (body) => client.post("/reports/templates", body).then((r) => r.data);
export const deleteReportTemplate = (templateId) =>
  client.delete(`/reports/templates/${templateId}`).then((r) => r.data);

// Notifiable disease reporting (P3.7). No public e-Notifikasi
// API exists -- these generate the notification + a PDF for a human to
// file at enotifikasi.moh.gov.my, and track whether that's been done.
export const listNotifiableDiseaseCandidates = () => client.get("/reports/notifiable-diseases/candidates").then((r) => r.data);
export const listNotifiableDiseaseReports = (status) =>
  client.get("/reports/notifiable-diseases", { params: { status: status || undefined } }).then((r) => r.data);
export const createNotifiableDiseaseReport = (body) => client.post("/reports/notifiable-diseases", body).then((r) => r.data);
export const markNotifiableDiseaseSubmitted = (reportId) =>
  client.post(`/reports/notifiable-diseases/${reportId}/submitted`).then((r) => r.data);
export const getNotifiableDiseaseDocumentBlob = (reportId) =>
  client.get(`/reports/notifiable-diseases/${reportId}/document`, { responseType: "blob" }).then((r) => r.data);

// Management Dashboard (P3.8, routers/dashboard.py). Facility-local, live-
// computed off existing rows -- no separate "refresh" action needed beyond
// re-fetching.
export const getDashboardSummary = () => client.get("/dashboard/summary").then((r) => r.data);
export const getDashboardFlowForecast = () => client.get("/dashboard/flow-forecast").then((r) => r.data);

export default client;
