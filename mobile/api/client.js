import axios from "axios";
import AsyncStorage from "@react-native-async-storage/async-storage";

// IMPORTANT: "localhost" will not work from a physical phone via Expo Go —
// use your computer's LAN IP (e.g. http://192.168.1.42:8000) or your
// deployed backend URL once you have one.
export const API_BASE = "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE });

client.interceptors.request.use(async (config) => {
  const token = await AsyncStorage.getItem("mb_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export async function login(email, password) {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  const { data } = await axios.post(`${API_BASE}/auth/login`, form.toString(), {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  await AsyncStorage.setItem("mb_token", data.access_token);
  await AsyncStorage.setItem("mb_user", JSON.stringify(data.user));
  return data;
}

export async function logout() {
  await AsyncStorage.removeItem("mb_token");
  await AsyncStorage.removeItem("mb_user");
}

export async function getCurrentUser() {
  const raw = await AsyncStorage.getItem("mb_user");
  return raw ? JSON.parse(raw) : null;
}

export const getPatient = (id) => client.get(`/patients/${id}`).then((r) => r.data);
export const getSummary = (id) => client.get(`/ai/summary/${id}`).then((r) => r.data);
export const issueEmergencyCard = (patientId, scope) =>
  client.post("/emergency/issue", { patient_id: patientId, scope }).then((r) => r.data);

export default client;
