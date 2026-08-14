import axios from "axios";

// Point this at your deployed backend URL before demo day.
export const API_BASE = "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("mb_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Any 401 that comes back through this client means the bearer token we
// just sent is no longer good — either it genuinely expired, or (now that
// changing a password revokes every other already-issued token for that
// account, see the backend JWT revocation work) it was invalidated by a
// password change on some other device/console. Whatever page triggered
// the call has no way to recover from that by itself, so we handle it once
// here globally: drop the stale token and send the user back to sign-in,
// instead of leaving every page on its own to keep re-hitting the same
// request and showing its own generic error forever.
//
// EXCEPTION: POST /auth/login returns a 401 for the completely ordinary
// "wrong email/NRIC or password" case — that is NOT a session problem, and
// Login.jsx's own try/catch already turns it into a proper on-page error
// message. If this interceptor fired for that response too, the user would
// never see that message; they'd just get silently bounced back to the
// login page they're already sitting on. The two OTP password-reset
// endpoints get the same exclusion defensively: they require no bearer
// token to begin with and 400 (not 401) on bad input per the backend, so a
// 401 from them shouldn't normally happen, but it's still not a "your
// session expired" case if it ever does.
const UNAUTHENTICATED_AUTH_PATHS = [
  "/auth/login",
  "/auth/request-password-reset-otp",
  "/auth/reset-password-with-otp",
];

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = error.config?.url || "";
    const isUnauthenticatedAuthCall = UNAUTHENTICATED_AUTH_PATHS.some((path) => requestUrl.includes(path));

    if (error.response?.status === 401 && !isUnauthenticatedAuthCall) {
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

    return Promise.reject(error);
  }
);

export async function login(email, password) {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  const { data } = await axios.post(`${API_BASE}/auth/login`, form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  localStorage.setItem("mb_token", data.access_token);
  localStorage.setItem("mb_user", JSON.stringify(data.user));
  return data;
}

export function logout() {
  localStorage.removeItem("mb_token");
  localStorage.removeItem("mb_user");
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

export const listPatients = () => client.get("/patients").then((r) => r.data);
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

export const getSummary = (id) => client.get(`/ai/summary/${id}`).then((r) => r.data);
export const getInteractionCheck = (id) => client.get(`/ai/interaction-check/${id}`).then((r) => r.data);
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
export const revokeNfcCard = (nfcUid) => client.post(`/emergency/nfc/revoke/${nfcUid}`).then((r) => r.data);

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
// MedicineInventoryOut) — never re-derive it client-side.
export const getAdminInventory = (lowStockOnly) =>
  client.get("/admin/inventory", { params: { low_stock_only: !!lowStockOnly } }).then((r) => r.data);
export const createInventoryItem = (payload) => client.post("/admin/inventory", payload).then((r) => r.data);
// Partial update — used both for the full edit modal and the quick +/-
// restock stepper (which sends just {quantity_on_hand}).
export const updateInventoryItem = (itemId, payload) => client.patch(`/admin/inventory/${itemId}`, payload).then((r) => r.data);
export const deleteInventoryItem = (itemId) => client.delete(`/admin/inventory/${itemId}`).then((r) => r.data);

// Ward / bed capacity. occupancy_pct and available_beds are server-computed
// (see WardOut) — never re-derive them client-side.
export const getWards = () => client.get("/admin/wards").then((r) => r.data);
export const createWard = (payload) => client.post("/admin/wards", payload).then((r) => r.data);
// Partial update — used both for the full edit modal and the quick +/-
// occupied-beds stepper (which sends just {occupied_beds}).
export const updateWard = (wardId, payload) => client.patch(`/admin/wards/${wardId}`, payload).then((r) => r.data);
export const deleteWard = (wardId) => client.delete(`/admin/wards/${wardId}`).then((r) => r.data);

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

export default client;
