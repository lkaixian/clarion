import { useSyncExternalStore } from "react";
import ms from "./lang/ms.json";
import zh from "./lang/zh.json";
import ta from "./lang/ta.json";

// Translation layer: the English text IS the key, so a string with no
// entry here simply shows in English and nothing breaks. Add a language by
// adding a block to DICT and an entry to LANGUAGES. The screen text lives in lang/*.json
// (keys = the English text found in tr("...") calls). Text that is built from
// variables is not covered and stays English.
export const LANGUAGES = [
  ["en", "English"],
  ["ms", "Bahasa Melayu"],
  ["zh", "中文"],
  ["ta", "தமிழ்"],
];

const HAND = {
  ms: {
    "Language": "Bahasa",
    "Skip to main content": "Langkau ke kandungan utama",
    "Care": "Rawatan", "Business": "Perniagaan", "System": "Sistem",
    "Patients": "Pesakit", "Reception": "Penerimaan", "Orders": "Pesanan", "Ancillary": "Perkhidmatan sokongan",
    "Dental": "Pergigian", "Pharmacy": "Farmasi", "Purchasing": "Perolehan", "Catalogue": "Katalog",
    "Billing": "Pengebilan", "Cashier": "Juruwang", "Reporting": "Pelaporan", "Dashboard": "Papan pemuka",
    "Forms": "Borang", "Admin Console": "Konsol Admin",
    "My record": "Rekod saya", "My bills": "Bil saya", "Sign out": "Log keluar",
    "Patient / public": "Pesakit / awam", "Staff": "Kakitangan",
    "NRIC or email": "NRIC atau e-mel", "Work email": "E-mel kerja", "Password": "Kata laluan",
    "Show": "Tunjuk", "Hide": "Sembunyi", "Show password": "Tunjukkan kata laluan",
    "Sign in": "Log masuk", "Signing in…": "Sedang log masuk…",
    "Caps Lock is on.": "Caps Lock dihidupkan.", "Forgot your password?": "Lupa kata laluan?",
  },
  zh: {
    "Language": "语言",
    "Skip to main content": "跳到主要内容",
    "Care": "诊疗", "Business": "业务", "System": "系统",
    "Patients": "患者", "Reception": "接待", "Orders": "医嘱", "Ancillary": "辅助检查",
    "Dental": "牙科", "Pharmacy": "药房", "Purchasing": "采购", "Catalogue": "目录",
    "Billing": "账单", "Cashier": "收银", "Reporting": "报表", "Dashboard": "仪表板",
    "Forms": "表格", "Admin Console": "管理控制台",
    "My record": "我的记录", "My bills": "我的账单", "Sign out": "退出登录",
    "Patient / public": "患者 / 公众", "Staff": "员工",
    "NRIC or email": "身份证号或电子邮件", "Work email": "工作邮箱", "Password": "密码",
    "Show": "显示", "Hide": "隐藏", "Show password": "显示密码",
    "Sign in": "登录", "Signing in…": "正在登录…",
    "Caps Lock is on.": "大写锁定已开启。", "Forgot your password?": "忘记密码？",
  },
  ta: {
    "Language": "மொழி",
    "Skip to main content": "முதன்மை உள்ளடக்கத்திற்குச் செல்",
    "Care": "பராமரிப்பு", "Business": "வணிகம்", "System": "அமைப்பு",
    "Patients": "நோயாளிகள்", "Reception": "வரவேற்பு", "Orders": "ஆணைகள்", "Ancillary": "துணை சேவைகள்",
    "Dental": "பல் மருத்துவம்", "Pharmacy": "மருந்தகம்", "Purchasing": "கொள்முதல்", "Catalogue": "பட்டியல்",
    "Billing": "கட்டணம்", "Cashier": "காசாளர்", "Reporting": "அறிக்கைகள்", "Dashboard": "முகப்புப் பலகை",
    "Forms": "படிவங்கள்", "Admin Console": "நிர்வாகக் கட்டுப்பாடு",
    "My record": "என் பதிவு", "My bills": "என் கட்டணங்கள்", "Sign out": "வெளியேறு",
    "Patient / public": "நோயாளி / பொதுமக்கள்", "Staff": "ஊழியர்",
    "NRIC or email": "NRIC அல்லது மின்னஞ்சல்", "Work email": "பணி மின்னஞ்சல்", "Password": "கடவுச்சொல்",
    "Show": "காட்டு", "Hide": "மறை", "Show password": "கடவுச்சொல்லைக் காட்டு",
    "Sign in": "உள்நுழை", "Signing in…": "உள்நுழைகிறது…",
    "Caps Lock is on.": "Caps Lock இயக்கத்தில் உள்ளது.", "Forgot your password?": "கடவுச்சொல்லை மறந்துவிட்டீர்களா?",
  },
};

// Generated screen-wide strings first, hand-written entries win on a clash.
const GENERATED = { ms, zh, ta };
const DICT = Object.fromEntries(
  Object.keys(GENERATED).map((code) => [code, { ...GENERATED[code], ...HAND[code] }]),
);

const KEY = "clarion_lang";
const listeners = new Set();

function initial() {
  try {
    const saved = localStorage.getItem(KEY);
    if (LANGUAGES.some(([code]) => code === saved)) return saved;
  } catch { /* storage blocked: stay on English */ }
  return "en";
}

let current = initial();
if (typeof document !== "undefined") document.documentElement.lang = current;

export function setLang(code) {
  if (!LANGUAGES.some(([c]) => c === code)) return;
  current = code;
  try { localStorage.setItem(KEY, code); } catch { /* per-session only */ }
  if (typeof document !== "undefined") document.documentElement.lang = code;
  listeners.forEach((fn) => fn());
}

export function translate(text, lang = current) {
  return DICT[lang]?.[text] ?? text;
}

// Plain (hook-free) lookup for use anywhere in JSX. The app root remounts when the
// language changes, so every tr() call re-evaluates.
export const tr = (text) => translate(text);

// Components that call this re-render when the language changes.
export function useLang() {
  const lang = useSyncExternalStore(
    (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    () => current,
  );
  return { lang, t: (text) => translate(text, lang) };
}
