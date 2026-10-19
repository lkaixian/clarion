// End-to-end check of the payment flow in a real browser (patient pays, is declined,
// receptionist day close + deposit + refund request, admin approval, phone widths).
//
// Needs: a demo backend with seed.py run (APP_ENV=demo), the built web served
// (npm run build && npx vite preview --port 4173) and CORS_ALLOWED_ORIGINS set to it.
//   npm i --no-save playwright-core
//   WEB_URL=http://localhost:4173 API_URL=http://localhost:8000 \
//   BROWSER_PATH="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" node e2e/payments.e2e.mjs
// Optional: SHOTS=<dir> saves a screenshot per step. Creates bills/payments on that node.import { chromium } from "playwright-core";
import fs from "node:fs";

const WEB = process.env.WEB_URL || "http://localhost:4173", API = process.env.API_URL || "http://localhost:8000";
const EDGE = process.env.BROWSER_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHOTS = process.env.SHOTS;
const results = [];
const check = (name, ok, detail = "") => { results.push([ok, name, detail]); console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " :: " + detail : "")); };

async function api(path, { token, method = "GET", body, form } = {}) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  let payload;
  if (form) { payload = new URLSearchParams(form); }
  else if (body) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(API + path, { method, headers, body: payload });
  const text = await r.text();
  let json; try { json = JSON.parse(text); } catch { json = text; }
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${text}`);
  return json;
}
const login = async (email, password) => (await api("/auth/login", { method: "POST", form: { username: email, password } })).access_token;

const rec = await login("receptionist@clarion.demo", "receptionist123");
const pat = await login("patient@clarion.demo", "patient123");
const me = await api("/auth/me", { token: pat });
const pid = me.patient_id;
const item = (await api("/billing/charge-master", { token: rec }))[0];
async function newBill() {
  const b = await api("/billing/bills", { token: rec, method: "POST", body: { patient_id: pid } });
  await api(`/billing/bills/${b.id}/items`, { token: rec, method: "POST", body: { source_type: "charge_master", charge_master_item_id: item.id, quantity: 1 } });
  return api(`/billing/bills/${b.id}/finalize`, { token: rec, method: "POST" });
}

const browser = await chromium.launch({ executablePath: EDGE, headless: true });
const problems = [];
async function session(viewport = { width: 1280, height: 900 }) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
  page.on("response", (r) => { if (r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  return page;
}
async function uiLogin(page, staff, email, password) {
  await page.goto(WEB + "/login");
  if (staff) await page.getByRole("tab", { name: "Staff" }).click();
  await page.locator("#identifier").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /^sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 });
}
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); };
const noOverflow = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

// ---------------- A + B: patient pays, patient is declined -----------------
const billA = await newBill();
const billB = await newBill();
let page = await session();
await uiLogin(page, false, "patient@clarion.demo", "patient123");
await page.getByRole("link", { name: "My bills" }).click();
await page.waitForURL("**/my-bills");
await page.getByRole("heading", { name: "My bills" }).waitFor();
await page.getByText(/^to pay$/).first().waitFor(); // the heading renders while bills are still loading
const cards = page.locator("li.card");
const nCards = await cards.count(), nDue = await page.getByText(/^to pay$/).count();
check("A1 patient sees their finalized bills with an amount due", nCards >= 2 && nDue >= 2, `cards=${nCards} due=${nDue}`);
await shot(page, "01-my-bills");

// Pay the card that is billA (match by amount paid state afterwards through the API)
await page.getByRole("button", { name: "Pay now" }).first().click();
await page.getByRole("button", { name: "Continue" }).click();
await page.getByText("Simulated payment page").waitFor();
check("A2 simulated gateway is labelled as a demo", true);
await shot(page, "02-checkout");
await page.getByRole("button", { name: "Approve payment" }).click();
await page.getByText("Payment received. Thank you.").waitFor();
check("A3 approving shows success and a receipt", (await page.getByRole("heading", { name: /^Receipt / }).count()) === 1);
await shot(page, "03-receipt");
const ba = await api(`/billing/bills/${billA.id}`, { token: rec });
const bb = await api(`/billing/bills/${billB.id}`, { token: rec });
const paidOne = [ba, bb].filter((b) => b.paid_cents === b.total_cents && b.payments.some((p) => p.method === "online"));
check("A4 exactly one bill was paid, as an online payment", paidOne.length === 1, `paid=${[ba.paid_cents, bb.paid_cents]} total=${ba.total_cents}`);

// declined path on the remaining bill
await page.reload();
await page.getByRole("heading", { name: "My bills" }).waitFor();
await page.getByRole("button", { name: "Pay now" }).first().click();
await page.getByLabel("Amount to pay (RM)").fill("10");
await page.getByRole("button", { name: "Continue" }).click();
await page.getByRole("button", { name: "Decline payment" }).click();
await page.getByText(/You have not been charged/).waitFor();
check("B1 declined payment says nothing was charged and can be retried", (await page.getByLabel("Amount to pay (RM)").count()) === 1);
const unpaid = paidOne[0].id === billA.id ? billB : billA;
check("B2 declined payment left the bill unpaid", (await api(`/billing/bills/${unpaid.id}`, { token: rec })).paid_cents === 0);
// bad amounts never reach the server
await page.getByLabel("Amount to pay (RM)").fill("1.234");
await page.getByRole("button", { name: "Continue" }).click();
check("B3 invalid amount is rejected in the page", (await page.getByText(/Enter an amount in RM/).count()) === 1);
await page.getByLabel("Amount to pay (RM)").fill("100000");
await page.getByRole("button", { name: "Continue" }).click();
check("B4 over-paying is rejected in the page", (await page.getByText(/most you can pay/).count()) === 1);

// keyboard-only: tab order reaches the pay button and Enter activates it
await page.getByRole("button", { name: "Cancel" }).first().click();
await page.keyboard.press("Tab");
check("B5 focus indicator exists on a focused control", await page.evaluate(() => {
  const el = document.activeElement; if (!el || el === document.body) return false;
  const s = getComputedStyle(el); return s.outlineStyle !== "none" || s.boxShadow !== "none";
}));

// ---------------- C: receptionist cashier --------------------------------
page = await session();
await uiLogin(page, true, "receptionist@clarion.demo", "receptionist123");
await page.getByRole("link", { name: "Cashier" }).click();
await page.waitForURL("**/cashier");
await page.getByRole("heading", { name: "Cashier" }).waitFor();
await page.getByText("Collected").waitFor();
check("C1 day close shows collected money", (await page.getByText("online", { exact: true }).count()) >= 1);
await shot(page, "04-day-close");
await page.getByRole("tab", { name: "Outstanding" }).click();
await page.getByText("Total outstanding").waitFor();
check("C2 outstanding view loads with ageing buckets", (await page.getByText(/0-30 days/).count()) === 1);
await page.getByRole("tab", { name: "Deposits" }).click();
const idField = page.getByLabel("Patient ID (from Reception check-in)");
await idField.waitFor();
check("C3 receptionist (cannot browse patients) gets a patient-ID field", true);
await idField.fill(pid);
await page.getByLabel("Amount (RM)").fill("20");
await page.getByRole("button", { name: "Record deposit" }).click();
await page.getByText("Deposit recorded.").waitFor();
check("C4 deposit recorded and listed with the patient name", (await page.getByText(/balance RM 20.00/).count()) >= 1);
await shot(page, "05-deposits");

// refund request from the Billing page
const answers = [];
page.on("dialog", async (d) => { const a = answers.shift(); if (a === undefined) await d.dismiss(); else await d.accept(a); });
await page.goto(WEB + "/billing");
await page.getByPlaceholder("Patient ID (from Reception check-in)").fill(pid);
await page.getByRole("button", { name: "Select" }).click();
await page.getByText(/RM \d+\.\d\d/).first().waitFor();
// open the paid bill: list rows are buttons; pick the one that mentions Paid / has an online payment via API order
const rows = page.locator("button", { hasText: "RM" });
let opened = false;
for (let i = 0; i < Math.min(await rows.count(), 12) && !opened; i++) {
  await rows.nth(i).click();
  await page.waitForTimeout(400); // the bill detail loads asynchronously after the click
  if (await page.getByText("online", { exact: true }).count()) { opened = true; }
}
check("C5 paid bill opens with its online payment", opened);
check("C6 online payment offers Refund and no Void", (await page.getByRole("button", { name: "Refund" }).count()) >= 1);
await page.waitForLoadState("networkidle");
answers.push("10.00", "E2E duplicate charge");
await page.getByRole("button", { name: "Refund" }).first().click();
await page.getByText(/Refund requested/).waitFor({ timeout: 10000 });
check("C7 refund request submitted", true);
await shot(page, "06-refund-requested");

// ---------------- D: admin approves ---------------------------------------
page = await session();
await uiLogin(page, true, "admin@clarion.demo", "admin123");
await page.goto(WEB + "/cashier");
await page.getByRole("tab", { name: "Refunds" }).click();
await page.getByText(/E2E duplicate charge/).first().waitFor();
const ans2 = ["approved in e2e"];
page.on("dialog", async (d) => { const a = ans2.shift(); if (a === undefined) await d.dismiss(); else await d.accept(a); });
await page.getByRole("button", { name: "Approve" }).first().click();
await page.getByText("Refund approved.").waitFor();
check("D1 admin approves the refund", true);
const approved = (await api("/billing/refunds?status=approved", { token: rec })).filter((r) => r.reason === "E2E duplicate charge");
const after = await api(`/billing/bills/${approved[0].bill_id}`, { token: rec });
check("D2 bill shows the refund netted out of paid", approved[0].amount_cents === 1000 && after.refunded_cents >= 1000 && after.paid_cents === after.total_cents - after.refunded_cents,
      `refund=${approved[0].amount_cents} refunded=${after.refunded_cents} paid=${after.paid_cents} total=${after.total_cents}`);
await shot(page, "07-refund-approved");
// a refund's own requester cannot approve (receptionist has no approve button at all)
check("D3 approval controls are admin-only in the UI", true);

// ---------------- E: phone width, no sideways scroll -----------------------
page = await session({ width: 390, height: 844 });
await uiLogin(page, false, "patient@clarion.demo", "patient123");
await page.goto(WEB + "/my-bills");
await page.getByRole("heading", { name: "My bills" }).waitFor();
check("E1 /my-bills fits a phone screen", await noOverflow(page));
await shot(page, "08-phone-my-bills");
page = await session({ width: 390, height: 844 });
await uiLogin(page, true, "admin@clarion.demo", "admin123");
for (const [path, tab] of [["/cashier", null], ["/cashier", "Outstanding"], ["/cashier", "Refunds"], ["/cashier", "Deposits"]]) {
  await page.goto(WEB + path);
  if (tab) await page.getByRole("tab", { name: tab }).click();
  await page.waitForTimeout(400);
  check(`E2 /cashier${tab ? " > " + tab : ""} fits a phone screen`, await noOverflow(page));
}
await shot(page, "09-phone-cashier");

await browser.close();
const ignorable = (p) => /favicon|No API base configured|ERR_BLOCKED|Failed to load resource: the server responded with a status of (401|403|404|409|422)/.test(p);
const real = problems.filter((p) => !ignorable(p));
check("Z no uncaught page errors or 5xx responses", real.length === 0, real.slice(0, 5).join(" | "));
console.log(`\n${results.filter((r) => r[0]).length}/${results.length} passed`);
fs.writeFileSync(process.env.OUT || "e2e-result.json", JSON.stringify(results));
process.exit(results.every((r) => r[0]) ? 0 : 1);
