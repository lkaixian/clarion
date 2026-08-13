import axios from "axios";

// Point this at your deployed backend URL before demo day.
export const API_BASE = "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("mb_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

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
export const getAuditLog = (id) => client.get(`/patients/${id}/audit-log`).then((r) => r.data);

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

export default client;
